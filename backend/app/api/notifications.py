"""REST API внутренних уведомлений, упоминаний, workload и настроек (v0.5.0).

Пользователь видит ТОЛЬКО свои уведомления; проектные дашборды/workload/mentions — под
project-гардом. Внешней доставки нет; live-публикаций/платежей нет; без секретов и внутренних
путей к файлам в ответах.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_notification_service, get_optional_user
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.notification_service import NotificationError, NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])

DbSession = Annotated[Session, Depends(get_db)]
NotifSvc = Annotated[NotificationService, Depends(get_notification_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except NotificationError as exc:
        message = str(exc)
        if "не найдено" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


# --- Запросы ---


class PreferenceRequest(BaseModel):
    """Настройка уведомления (канал/тип/включено)."""

    channel: str = "in_app"
    notification_type: str | None = None
    enabled: bool = True


# --- Уведомления пользователя ---


@router.get("")
def list_notifications(
    db: DbSession,
    service: NotifSvc,
    user: CurrentUser,
    status_filter: str | None = None,
    notification_type: str | None = None,
    priority: str | None = None,
    project_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """Inbox текущего пользователя (фильтры статус/тип/приоритет/проект)."""
    return service.build_user_inbox(
        db,
        user.id,
        status=status_filter,
        notification_type=notification_type,
        priority=priority,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@router.get("/unread-count")
def unread_count(db: DbSession, service: NotifSvc, user: CurrentUser) -> dict[str, int]:
    """Число непрочитанных уведомлений текущего пользователя."""
    return {"unread_count": service.unread_count(db, user.id)}


@router.post("/read-all")
def read_all(
    db: DbSession, service: NotifSvc, user: CurrentUser, project_id: int | None = None
) -> dict[str, Any]:
    """Отметить все непрочитанные текущего пользователя прочитанными."""
    return service.mark_all_read(db, user.id, project_id)


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int, db: DbSession, service: NotifSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отметить уведомление прочитанным (только получатель)."""
    return _run(lambda: service.mark_read(db, notification_id, user.id))


@router.post("/{notification_id}/dismiss")
def dismiss(
    notification_id: int, db: DbSession, service: NotifSvc, user: CurrentUser
) -> dict[str, Any]:
    """Скрыть уведомление (только получатель)."""
    return _run(lambda: service.dismiss(db, notification_id, user.id))


# --- Настройки ---


@router.get("/preferences")
def get_preferences(db: DbSession, service: NotifSvc, user: CurrentUser) -> dict[str, Any]:
    """Настройки уведомлений текущего пользователя (+ безопасные дефолты каналов)."""
    return service.get_preferences(db, user.id)


@router.post("/preferences")
def set_preference(
    payload: PreferenceRequest, db: DbSession, service: NotifSvc, user: CurrentUser
) -> dict[str, Any]:
    """Задать настройку уведомления. Внешние каналы нельзя включить без внешней доставки."""
    return _run(
        lambda: service.set_preference(
            db, user.id, payload.channel, payload.enabled, payload.notification_type
        )
    )


# --- Проектные дашборды (project-гард) ---


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def project_dashboard(project_id: int, db: DbSession, service: NotifSvc) -> dict[str, Any]:
    """Сводка уведомлений проекта (непрочитанные/overdue/по типу/high-urgent)."""
    return service.build_project_notification_dashboard(db, project_id)


@router.get("/projects/{project_id}/workload", dependencies=[Depends(require_project_access)])
def project_workload(project_id: int, db: DbSession, service: NotifSvc) -> dict[str, Any]:
    """Нагрузка ревьюеров проекта (assigned/overdue/high-urgent/avg age/SLA)."""
    return service.build_review_workload(db, project_id)


@router.get("/projects/{project_id}/mentions", dependencies=[Depends(require_project_access)])
def project_mentions(
    project_id: int, db: DbSession, service: NotifSvc, mention_status: str | None = None
) -> list[dict[str, Any]]:
    """Упоминания проекта (для дашборда)."""
    return service.list_project_mentions(db, project_id, status=mention_status)


@router.post(
    "/projects/{project_id}/overdue-scan-dry", dependencies=[Depends(require_project_access)]
)
def overdue_scan_dry(project_id: int, db: DbSession, service: NotifSvc) -> dict[str, Any]:
    """Dry-run скан просроченных задач ревью (без записи уведомлений)."""
    return service.notify_overdue_tasks(db, project_id, dry_run=True)
