"""REST API SaaS-онбординга: форма, preview/apply, проекты аккаунта, дашборд.

Переиспользует CRM-конфигуратор (валидация/apply/секреты/live-off). Публикаций
нет; live-публикация остаётся выключенной. Auth-мидлвар — задача следующего этапа
(см. ``get_current_account`` в ``auth_service``); эндпоинты принимают ``account_id``.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_saas_bot_run_service, get_saas_onboarding_service
from app.api.security_guards import (
    OptionalUser,
    SettingsDep,
    guard_account_in_body,
    require_account_member,
    require_project_access,
)
from app.schemas.crm_bot_smm import BotSmmFormSchema
from app.schemas.saas_onboarding import (
    ProjectDashboard,
    SaasBotRunResult,
    SaasOnboardingRequest,
    SaasOnboardingResult,
    SaasProjectSummary,
    SaasRunRequest,
)
from app.services.billing_service import InsufficientBalanceError
from app.services.crm_bot_smm_form_service import CrmOnboardingValidationError
from app.services.saas_bot_run_service import SaasBotRunError, SaasBotRunService
from app.services.saas_onboarding_service import SaasOnboardingError, SaasOnboardingService

router = APIRouter(prefix="/saas", tags=["saas"])

DbSession = Annotated[Session, Depends(get_db)]
OnboardingSvc = Annotated[SaasOnboardingService, Depends(get_saas_onboarding_service)]
RunSvc = Annotated[SaasBotRunService, Depends(get_saas_bot_run_service)]


@router.get("/onboarding/form-schema", response_model=BotSmmFormSchema)
def form_schema(service: OnboardingSvc) -> BotSmmFormSchema:
    """JSON-схема SaaS-формы личного кабинета."""
    return service.build_form_schema()


@router.post("/onboarding/preview", response_model=SaasOnboardingResult)
def preview(
    payload: SaasOnboardingRequest,
    db: DbSession,
    service: OnboardingSvc,
    user: OptionalUser,
    settings: SettingsDep,
) -> SaasOnboardingResult:
    """Dry-run: валидирует и показывает, что будет создано (без записи)."""
    guard_account_in_body(db, settings, user, payload.account_id)
    try:
        return service.preview(db, payload.account_id, payload.payload, payload.allow_live)
    except CrmOnboardingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(exc.errors)
        ) from exc
    except SaasOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/onboarding/apply", response_model=SaasOnboardingResult)
def apply(
    payload: SaasOnboardingRequest,
    db: DbSession,
    service: OnboardingSvc,
    user: OptionalUser,
    settings: SettingsDep,
) -> SaasOnboardingResult:
    """Реальный apply: создаёт проект/конфиг под аккаунтом + провижининг биллинга."""
    guard_account_in_body(db, settings, user, payload.account_id)
    try:
        return service.apply(db, payload.account_id, payload.payload, payload.allow_live)
    except CrmOnboardingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="; ".join(exc.errors)
        ) from exc
    except SaasOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/accounts/{account_id}/projects",
    response_model=list[SaasProjectSummary],
    dependencies=[Depends(require_account_member)],
)
def list_account_projects(
    account_id: int, db: DbSession, service: OnboardingSvc
) -> list[SaasProjectSummary]:
    """Проекты, привязанные к аккаунту."""
    projects = service.list_account_projects(db, account_id)
    return [SaasProjectSummary.model_validate(p) for p in projects]


@router.get(
    "/projects/{project_id}/dashboard",
    response_model=ProjectDashboard,
    dependencies=[Depends(require_project_access)],
)
def project_dashboard(project_id: int, db: DbSession, service: OnboardingSvc) -> ProjectDashboard:
    """Дашборд проекта (конфигурация, контент, ревью, биллинг, рекомендации)."""
    try:
        return service.build_dashboard(db, project_id)
    except SaasOnboardingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/run-dry",
    response_model=SaasBotRunResult,
    dependencies=[Depends(require_project_access)],
)
def run_project_dry(
    project_id: int,
    payload: SaasRunRequest,
    db: DbSession,
    service: RunSvc,
    user: OptionalUser,
    settings: SettingsDep,
) -> SaasBotRunResult:
    """Dry-run прогон проекта: только оценка units, без списания и без постов."""
    guard_account_in_body(db, settings, user, payload.account_id)
    try:
        return service.run_project_dry_preview(
            db, payload.account_id, project_id, payload.category_id
        )
    except SaasBotRunError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/run-semi-auto",
    response_model=SaasBotRunResult,
    dependencies=[Depends(require_project_access)],
)
def run_project_semi_auto(
    project_id: int,
    payload: SaasRunRequest,
    db: DbSession,
    service: RunSvc,
    user: OptionalUser,
    settings: SettingsDep,
) -> SaasBotRunResult:
    """Semi-auto прогон: проверка баланса → посты на ревью → списание units. Без публикаций."""
    guard_account_in_body(db, settings, user, payload.account_id)
    try:
        return service.run_project_semi_auto(
            db, payload.account_id, project_id, payload.category_id
        )
    except SaasBotRunError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
