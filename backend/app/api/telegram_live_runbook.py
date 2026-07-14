"""REST API Telegram live production runbook — v0.6.3.

Клиентский «запуск Telegram автопилота»: дашборд готовности, проверка чек-листа, preview тестового
поста, ручной production-тест (под всеми гейтами rollout-сервиса), пауза. Всё под project-гардом.
Секретов/сырых токенов в ответах нет; API НЕ включает и НЕ обходит глобальные live-флаги.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_telegram_live_runbook_service
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.telegram_live_runbook_service import (
    TelegramLiveRunbookError,
    TelegramLiveRunbookService,
)

router = APIRouter(prefix="/projects", tags=["telegram-live-runbook"])

DbSession = Annotated[Session, Depends(get_db)]
RunbookSvc = Annotated[TelegramLiveRunbookService, Depends(get_telegram_live_runbook_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except TelegramLiveRunbookError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class TestPostRequest(BaseModel):
    """Параметры preview/публикации тестового поста (пост + подтверждение)."""

    post_id: int | None = None
    confirmation: str = ""


@router.get("/{project_id}/telegram-runbook", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: RunbookSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд runbook (чек-лист, статус, история попыток)."""
    return _run(lambda: service.build_dashboard(db, project_id))


@router.post("/{project_id}/telegram-runbook/check", dependencies=[Depends(require_project_access)])
def check(project_id: int, db: DbSession, service: RunbookSvc, user: CurrentUser) -> dict[str, Any]:
    """Проверить готовность и сохранить чек-лист runbook."""
    return _run(
        lambda: service.build_checklist(db, project_id, current_user_id=user.id, dry_run=False)
    )


@router.post(
    "/{project_id}/telegram-runbook/preview", dependencies=[Depends(require_project_access)]
)
def preview(
    project_id: int,
    payload: TestPostRequest,
    db: DbSession,
    service: RunbookSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Собрать preview тестового поста (без отправки)."""
    return _run(
        lambda: service.prepare_test_post(
            db, project_id, post_id=payload.post_id, current_user_id=user.id
        )
    )


@router.post(
    "/{project_id}/telegram-runbook/publish-test", dependencies=[Depends(require_project_access)]
)
def publish_test(
    project_id: int,
    payload: TestPostRequest,
    db: DbSession,
    service: RunbookSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Ручной production-тест: одна реальная публикация (только под всеми гейтами)."""
    return _run(
        lambda: service.publish_test_post(
            db,
            project_id,
            post_id=payload.post_id,
            confirmation_text=payload.confirmation,
            current_user_id=user.id,
        )
    )


@router.post("/{project_id}/telegram-runbook/pause", dependencies=[Depends(require_project_access)])
def pause(project_id: int, db: DbSession, service: RunbookSvc, user: CurrentUser) -> dict[str, Any]:
    """Поставить runbook на паузу (блокирует production-тест)."""
    return _run(lambda: service.pause_runbook(db, project_id, current_user_id=user.id))
