"""REST API Telegram-first live rollout — v0.6.0.

Клиентский слой «Telegram — первый live-канал»: дашборд, история попыток, preview, тестовый прогон
без отправки, однократная реальная публикация (по умолчанию заблокирована), эффективный статус. Всё
под project-гардом. Секретов/сырых токенов в ответах нет; API НЕ включает и НЕ обходит глобальные
live-флаги; реальная отправка возможна только под всеми гейтами; ``publish_due`` не вызывается.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_telegram_live_rollout_service
from app.api.security_guards import require_live_attempt_access, require_project_access
from app.models.user import User
from app.services.telegram_live_rollout_service import (
    TelegramLiveRolloutError,
    TelegramLiveRolloutService,
)

router = APIRouter(prefix="/telegram-live-rollout", tags=["telegram-live-rollout"])

DbSession = Annotated[Session, Depends(get_db)]
RolloutSvc = Annotated[TelegramLiveRolloutService, Depends(get_telegram_live_rollout_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except TelegramLiveRolloutError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class RunRequest(BaseModel):
    """Параметры preview/dry-run/publish (пост или публикация + подтверждение)."""

    post_id: int | None = None
    publication_id: int | None = None
    confirmation: str = ""


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: RolloutSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд Telegram live rollout."""
    return _run(lambda: service.build_dashboard(db, project_id))


@router.get("/projects/{project_id}/attempts", dependencies=[Depends(require_project_access)])
def list_attempts(
    project_id: int, db: DbSession, service: RolloutSvc, user: CurrentUser, limit: int = 100
) -> dict[str, Any]:
    """История live/dry-run попыток проекта."""
    return _run(lambda: service.list_attempts(db, project_id, limit=limit))


@router.get("/attempts/{attempt_id}", dependencies=[Depends(require_live_attempt_access)])
def attempt_detail(
    attempt_id: int, db: DbSession, service: RolloutSvc, user: CurrentUser
) -> dict[str, Any]:
    """Детали попытки (доступ проверяется через attempt.project_id)."""
    return _run(lambda: service.get_attempt_detail(db, attempt_id))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int,
    payload: RunRequest,
    db: DbSession,
    service: RolloutSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Предпросмотр Telegram-публикации (без записи и без сети)."""
    return _run(
        lambda: service.preview_post(db, project_id, payload.post_id, current_user_id=user.id)
    )


@router.post("/projects/{project_id}/run-dry", dependencies=[Depends(require_project_access)])
def run_dry(
    project_id: int,
    payload: RunRequest,
    db: DbSession,
    service: RolloutSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Тестовый прогон без отправки (создаёт attempt, без списания)."""
    return _run(
        lambda: service.run_once_dry(
            db,
            project_id,
            post_id=payload.post_id,
            publication_id=payload.publication_id,
            current_user_id=user.id,
        )
    )


@router.post(
    "/projects/{project_id}/publish-once-if-allowed",
    dependencies=[Depends(require_project_access)],
)
def publish_once_if_allowed(
    project_id: int,
    payload: RunRequest,
    db: DbSession,
    service: RolloutSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Однократная реальная публикация — по умолчанию заблокирована (allow_real_send=false)."""
    return _run(
        lambda: service.publish_once_if_allowed(
            db,
            project_id,
            post_id=payload.post_id,
            publication_id=payload.publication_id,
            confirmation=payload.confirmation,
            current_user_id=user.id,
        )
    )


@router.get(
    "/projects/{project_id}/effective-status", dependencies=[Depends(require_project_access)]
)
def effective_status(
    project_id: int, db: DbSession, service: RolloutSvc, user: CurrentUser
) -> dict[str, Any]:
    """Эффективный статус Telegram live (все гейты + allow_real_send)."""
    return _run(lambda: service.build_effective_telegram_live_status(db, project_id))
