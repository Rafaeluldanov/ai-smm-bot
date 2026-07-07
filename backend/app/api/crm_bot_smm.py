"""REST API слоя «CRM Bot SMM Onboarding / Configurator».

CRM открывает форму (``form-schema``), сохраняет черновик, валидирует, смотрит
превью и применяет онбординг (``apply``). Затем по категориям строит контент-план
и запускает БЕЗОПАСНЫЙ semi_auto/dry-run.

Безопасность эндпоинтов:
- ``test-connection`` не ходит в сеть и не печатает секрет (offline dry-run);
- ``run-dry`` не создаёт постов; ``run-semi-auto`` создаёт посты в статусе
  needs_review и НЕ публикует; live VK/TG выключены.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_crm_bot_smm_application_service,
    get_crm_bot_smm_form_service,
    get_db,
)
from app.models.crm_bot_smm import CrmBotProjectConfig
from app.repositories import crm_bot_smm_repository as repo
from app.repositories import project_repository
from app.schemas.crm_bot_smm import (
    BotSmmFormSchema,
    CrmBotProjectConfigRead,
    CrmBotProjectConfigUpdate,
    CrmCategoryRunPreview,
    CrmCategoryRunResult,
    CrmConnectionTestRequest,
    CrmConnectionTestResult,
    CrmOnboardingDraftCreate,
    CrmOnboardingDraftRead,
    CrmOnboardingDraftUpdate,
    CrmPreviewResult,
    CrmValidationResult,
)
from app.schemas.seo import SeoContentPlan
from app.services.crm_bot_smm_application_service import (
    CrmBotSmmApplicationService,
    CrmCategoryNotFoundError,
    CrmConfigNotFoundError,
)
from app.services.crm_bot_smm_form_service import (
    CrmBotSmmFormService,
    CrmOnboardingValidationError,
)

router = APIRouter(prefix="/crm/bot-smm", tags=["crm-bot-smm"])

T = TypeVar("T")

DbSession = Annotated[Session, Depends(get_db)]
FormService = Annotated[CrmBotSmmFormService, Depends(get_crm_bot_smm_form_service)]
AppService = Annotated[CrmBotSmmApplicationService, Depends(get_crm_bot_smm_application_service)]


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


# --------------------------------------------------------------------------- #
# Схема формы                                                                 #
# --------------------------------------------------------------------------- #


@router.get("/form-schema", response_model=BotSmmFormSchema)
def get_form_schema(service: FormService) -> BotSmmFormSchema:
    """JSON-схема формы «БОТ СММ» для отрисовки в CRM (без БД)."""
    return service.build_form_schema()


# --------------------------------------------------------------------------- #
# Черновики онбординга                                                         #
# --------------------------------------------------------------------------- #


@router.post(
    "/onboarding-drafts",
    response_model=CrmOnboardingDraftRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft(payload: CrmOnboardingDraftCreate, db: DbSession) -> CrmOnboardingDraftRead:
    """Создать черновик онбординга."""
    draft = repo.create_draft(db, payload)
    return CrmOnboardingDraftRead.model_validate(draft)


@router.get("/onboarding-drafts/{draft_id}", response_model=CrmOnboardingDraftRead)
def get_draft(draft_id: int, db: DbSession) -> CrmOnboardingDraftRead:
    """Получить черновик онбординга по id (404, если нет)."""
    draft = repo.get_draft_by_id(db, draft_id)
    if draft is None:
        raise _not_found(f"Черновик id={draft_id} не найден")
    return CrmOnboardingDraftRead.model_validate(draft)


@router.patch("/onboarding-drafts/{draft_id}", response_model=CrmOnboardingDraftRead)
def update_draft(
    draft_id: int, payload: CrmOnboardingDraftUpdate, db: DbSession
) -> CrmOnboardingDraftRead:
    """Частично обновить черновик онбординга (404, если нет)."""
    draft = repo.get_draft_by_id(db, draft_id)
    if draft is None:
        raise _not_found(f"Черновик id={draft_id} не найден")
    return CrmOnboardingDraftRead.model_validate(repo.update_draft(db, draft, payload))


@router.post("/onboarding-drafts/{draft_id}/validate", response_model=CrmValidationResult)
def validate_draft(draft_id: int, db: DbSession, service: FormService) -> CrmValidationResult:
    """Проверить пейлоад черновика (200 всегда; ошибки — в теле ответа)."""
    draft = repo.get_draft_by_id(db, draft_id)
    if draft is None:
        raise _not_found(f"Черновик id={draft_id} не найден")
    result = service.validate_onboarding_payload(draft.payload)
    repo.update_draft(
        db,
        draft,
        CrmOnboardingDraftUpdate(
            validation_errors=result.errors,
            status="validated" if result.valid else "draft",
        ),
    )
    return result


@router.post("/onboarding-drafts/{draft_id}/preview", response_model=CrmPreviewResult)
def preview_draft(draft_id: int, db: DbSession, service: FormService) -> CrmPreviewResult:
    """Превью онбординга (dry-run; ничего не пишет). 422 — невалидный пейлоад."""
    draft = repo.get_draft_by_id(db, draft_id)
    if draft is None:
        raise _not_found(f"Черновик id={draft_id} не найден")
    try:
        return service.apply_onboarding_payload(db, draft.payload, dry_run=True)
    except CrmOnboardingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors
        ) from exc


@router.post("/onboarding-drafts/{draft_id}/apply", response_model=CrmPreviewResult)
def apply_draft(
    draft_id: int,
    db: DbSession,
    service: FormService,
    dry_run: Annotated[bool, Query(description="dry-run: ничего не пишет")] = True,
) -> CrmPreviewResult:
    """Применить онбординг. dry_run=true — превью; false — создать записи.

    Публикаций не выполняет. 422 — невалидный пейлоад.
    """
    draft = repo.get_draft_by_id(db, draft_id)
    if draft is None:
        raise _not_found(f"Черновик id={draft_id} не найден")
    try:
        result = service.apply_onboarding_payload(db, draft.payload, dry_run=dry_run)
    except CrmOnboardingValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors
        ) from exc

    if not dry_run and result.config_id is not None:
        config = repo.get_config_by_id(db, result.config_id)
        repo.update_draft(
            db,
            draft,
            CrmOnboardingDraftUpdate(
                status="applied",
                project_id=config.project_id if config is not None else None,
                validation_errors=[],
            ),
        )
    return result


# --------------------------------------------------------------------------- #
# Конфигурация проекта                                                         #
# --------------------------------------------------------------------------- #


def _get_config_or_404(db: Session, project_id: int) -> CrmBotProjectConfig:
    if project_repository.get_project_by_id(db, project_id) is None:
        raise _not_found(f"Проект id={project_id} не найден")
    config = repo.get_config_by_project_id(db, project_id)
    if config is None:
        raise _not_found(f"Конфигурация для проекта id={project_id} не найдена")
    return config


@router.get("/projects/{project_id}/config", response_model=CrmBotProjectConfigRead)
def get_project_config(project_id: int, db: DbSession) -> CrmBotProjectConfigRead:
    """Получить конфигурацию проекта (404, если проекта/конфигурации нет)."""
    return CrmBotProjectConfigRead.model_validate(_get_config_or_404(db, project_id))


@router.patch("/projects/{project_id}/config", response_model=CrmBotProjectConfigRead)
def update_project_config(
    project_id: int, payload: CrmBotProjectConfigUpdate, db: DbSession
) -> CrmBotProjectConfigRead:
    """Частично обновить конфигурацию проекта (404, если нет)."""
    config = _get_config_or_404(db, project_id)
    return CrmBotProjectConfigRead.model_validate(repo.update_config(db, config, payload))


# --------------------------------------------------------------------------- #
# Тест подключения ресурса (безопасный, без сети и секретов)                   #
# --------------------------------------------------------------------------- #


@router.post("/resources/{resource_id}/test-connection", response_model=CrmConnectionTestResult)
def test_resource_connection(
    resource_id: int,
    db: DbSession,
    payload: CrmConnectionTestRequest | None = None,
) -> CrmConnectionTestResult:
    """Безопасно проверить конфигурацию ресурса.

    Сеть НЕ вызывается и секрет НЕ печатается. VK groups.getById возможен только
    в реальной среде и только при ``test_connection=true`` — здесь выполняется
    безопасный offline dry-run.
    """
    resource = repo.get_resource_by_id(db, resource_id)
    if resource is None:
        raise _not_found(f"Ресурс id={resource_id} не найден")

    request = payload or CrmConnectionTestRequest()
    warnings: list[str] = []
    ok = True
    detail = "Конфигурация ресурса выглядит корректной (offline-проверка)."

    if resource.resource_type == "vk":
        if not (resource.external_id or resource.url):
            ok = False
            detail = "Для VK нужен external_id (group_id) или url."
        elif request.test_connection:
            detail = (
                "VK groups.getById доступен только в реальной среде; выполнен "
                "безопасный dry-run (сеть не вызывалась)."
            )
    elif resource.resource_type == "yandex_disk" and not resource.yandex_public_url:
        ok = False
        detail = "Для Яндекс Диска нужен yandex_public_url."
    if not resource.api_key_encrypted:
        warnings.append("Секрет ресурса не задан (api_key отсутствует).")

    return CrmConnectionTestResult(
        resource_id=resource.id,
        resource_type=resource.resource_type,
        performed=False,
        ok=ok,
        api_key_present=bool(resource.api_key_encrypted),
        api_key_masked=resource.api_key_masked,
        detail=detail,
        warnings=warnings,
    )


# --------------------------------------------------------------------------- #
# Категории: контент-план и безопасные прогоны                                 #
# --------------------------------------------------------------------------- #


def _category_action(action: Callable[[], T]) -> T:
    """Привести доменные ошибки категории/конфигурации к 404."""
    try:
        return action()
    except (CrmCategoryNotFoundError, CrmConfigNotFoundError) as exc:
        raise _not_found(str(exc)) from exc


@router.post("/categories/{category_id}/preview-plan", response_model=SeoContentPlan)
def preview_category_plan(
    category_id: int,
    db: DbSession,
    service: AppService,
    days: Annotated[int, Query(ge=1, le=180)] = 30,
) -> SeoContentPlan:
    """Контент-план категории на N дней (каждый день — со ссылкой на сайт)."""
    return _category_action(
        lambda: service.build_content_plan_from_category(db, category_id, days=days)
    )


@router.post("/categories/{category_id}/run-dry", response_model=CrmCategoryRunResult)
def run_category_dry(category_id: int, db: DbSession, service: AppService) -> CrmCategoryRunResult:
    """Сухой прогон категории (без создания постов и публикаций)."""
    return _category_action(lambda: service.run_category_semi_auto(db, category_id, dry_run=True))


@router.post("/categories/{category_id}/run-semi-auto", response_model=CrmCategoryRunResult)
def run_category_semi_auto(
    category_id: int, db: DbSession, service: AppService
) -> CrmCategoryRunResult:
    """Semi-auto прогон: создаёт посты (needs_review), НЕ публикует."""
    return _category_action(lambda: service.run_category_semi_auto(db, category_id, dry_run=False))


@router.get("/categories/{category_id}/run-preview", response_model=CrmCategoryRunPreview)
def preview_category_run(
    category_id: int, db: DbSession, service: AppService
) -> CrmCategoryRunPreview:
    """Показать, что будет запущено по категории (без записи в БД)."""
    return _category_action(lambda: service.preview_category_run(db, category_id))
