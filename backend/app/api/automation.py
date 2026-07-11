"""REST API режима автоматизации и обучения (v0.4.0).

- ``/automation/...`` — чтение/запись режима (semi_auto|full_auto) на уровне проекта/
  платформы/плана. Включение full_auto требует подтверждения ``ENABLE_FULL_AUTO`` и НЕ
  означает live-публикацию (та проходит отдельные safety gates).
- ``/learning/...`` — блок «Чему бот научился»: сводка профиля, подсказки тем, ручной
  пересчёт (платное действие). Секретов в ответах нет; tenant-изоляция обязательна.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_user
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.automation_settings_service import (
    AutomationPlanNotFoundError,
    AutomationSettingsError,
    AutomationSettingsService,
    get_automation_settings_service,
)
from app.services.billing_service import (
    USAGE_LEARNING_PROFILE_REBUILD,
    BillingService,
    InsufficientBalanceError,
)
from app.services.client_learning_service import (
    ClientLearningService,
    get_client_learning_service,
)

router = APIRouter(tags=["automation-learning"])

DbSession = Annotated[Session, Depends(get_db)]
AutoSvc = Annotated[AutomationSettingsService, Depends(get_automation_settings_service)]
LearnSvc = Annotated[ClientLearningService, Depends(get_client_learning_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AutomationPlanNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AutomationSettingsError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


# --- Запросы ---


class AutomationSettingsPayload(BaseModel):
    """Настройки режима автоматизации (все поля опциональны)."""

    automation_mode: str | None = None  # semi_auto | full_auto
    auto_publish_enabled: bool | None = None
    learning_enabled: bool | None = None
    require_review_before_first_auto: bool | None = None
    min_quality_score_for_auto: int | None = Field(default=None, ge=0, le=100)
    max_posts_per_day_auto: int | None = Field(default=None, ge=0)
    # Подтверждение для включения full_auto/авто-публикации.
    confirm: str | None = None


# --- Automation settings ---


@router.get(
    "/automation/projects/{project_id}/settings",
    dependencies=[Depends(require_project_access)],
)
def get_project_automation(project_id: int, db: DbSession, service: AutoSvc) -> dict[str, Any]:
    """Сводка режима автоматизации проекта + готовность профиля обучения."""
    return service.get_project_settings(db, project_id)


@router.post(
    "/automation/projects/{project_id}/settings",
    dependencies=[Depends(require_project_access)],
)
def set_project_automation(
    project_id: int,
    payload: AutomationSettingsPayload,
    db: DbSession,
    service: AutoSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Применить режим ко всем планам проекта. full_auto требует confirm=ENABLE_FULL_AUTO."""
    body = payload.model_dump(exclude={"confirm"}, exclude_none=True)
    return _run(
        lambda: service.update_project_settings(
            db, project_id, body, user_id=_uid(user), confirm=payload.confirm
        )
    )


@router.get(
    "/automation/projects/{project_id}/platforms/{platform_key}/settings",
    dependencies=[Depends(require_project_access)],
)
def get_platform_automation(
    project_id: int, platform_key: str, db: DbSession, service: AutoSvc
) -> dict[str, Any]:
    """Режим автоматизации по планам, включающим площадку."""
    return service.get_platform_settings(db, project_id, platform_key)


@router.post(
    "/automation/projects/{project_id}/platforms/{platform_key}/settings",
    dependencies=[Depends(require_project_access)],
)
def set_platform_automation(
    project_id: int,
    platform_key: str,
    payload: AutomationSettingsPayload,
    db: DbSession,
    service: AutoSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Применить режим к планам площадки. full_auto требует confirm=ENABLE_FULL_AUTO."""
    body = payload.model_dump(exclude={"confirm"}, exclude_none=True)
    return _run(
        lambda: service.update_platform_settings(
            db, project_id, platform_key, body, user_id=_uid(user), confirm=payload.confirm
        )
    )


@router.post(
    "/automation/projects/{project_id}/plans/{plan_id}/mode",
    dependencies=[Depends(require_project_access)],
)
def set_plan_mode(
    project_id: int,
    plan_id: int,
    payload: AutomationSettingsPayload,
    db: DbSession,
    service: AutoSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Задать режим одного плана. full_auto требует confirm=ENABLE_FULL_AUTO."""
    body = payload.model_dump(exclude={"confirm"}, exclude_none=True)
    return _run(
        lambda: service.set_plan_mode(
            db, project_id, plan_id, body, user_id=_uid(user), confirm=payload.confirm
        )
    )


# --- Learning («Чему бот научился») ---


@router.get(
    "/learning/projects/{project_id}/summary",
    dependencies=[Depends(require_project_access)],
)
def learning_summary(
    project_id: int, db: DbSession, service: LearnSvc, platform: str | None = None
) -> dict[str, Any]:
    """Сводка «Чему бот научился» (темы/CTA/теги/уверенность/рекомендации)."""
    return service.summarize_learning(db, project_id, platform)


@router.get(
    "/learning/projects/{project_id}/suggested-topics",
    dependencies=[Depends(require_project_access)],
)
def suggested_topics(
    project_id: int, db: DbSession, service: LearnSvc, platform: str | None = None, limit: int = 10
) -> dict[str, Any]:
    """Темы, которые бот будет предлагать чаще (по профилю обучения)."""
    return {
        "project_id": project_id,
        "topics": service.suggest_next_topics(db, project_id, platform, limit),
    }


@router.post(
    "/learning/projects/{project_id}/rebuild",
    dependencies=[Depends(require_project_access)],
)
def rebuild_profile(
    project_id: int,
    db: DbSession,
    service: LearnSvc,
    user: OptUser,
    platform: str | None = None,
) -> dict[str, Any]:
    """Глубокий пересчёт профиля с поднятием версии (платно: 5 units).

    Аккаунт для списания берётся ИЗ проекта (project.account_id), а не из запроса —
    иначе можно было бы списать units с чужого аккаунта (tenant-изоляция).
    """
    from app.repositories import project_repository

    project = project_repository.get_project_by_id(db, project_id)
    account_id = project.account_id if project is not None else None
    billing = BillingService()
    units = billing.estimate_action_cost(USAGE_LEARNING_PROFILE_REBUILD)
    if account_id is not None:
        try:
            billing.ensure_balance(db, account_id, units)
        except InsufficientBalanceError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)
            ) from exc
    profile = service.rebuild_learning_profile(db, project_id, platform)
    charged = 0
    if account_id is not None:
        ledger = billing.debit_for_action(
            db,
            account_id,
            units=units,
            usage_type=USAGE_LEARNING_PROFILE_REBUILD,
            idempotency_key=f"learning-rebuild-{project_id}-v{profile.profile_version}",
            project_id=project_id,
        )
        charged = units if ledger is not None else 0
    return {
        "project_id": project_id,
        "profile_version": profile.profile_version,
        "confidence_score": round(profile.confidence_score, 3),
        "units_charged": charged,
    }
