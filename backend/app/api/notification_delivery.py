"""REST API доставки уведомлений (sandbox) и дайджестов (v0.5.1).

Пользователь видит ТОЛЬКО свои delivery-логи/дайджесты; проектный дашборд — под project-гардом.
Реальная внешняя доставка выключена: send-dry всегда sandbox; реальный send отказывает, пока
внешняя доставка выключена. Без секретов/токенов и внешних вызовов по умолчанию.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_db,
    get_notification_delivery_service,
    get_notification_digest_service,
)
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.notification_delivery_service import (
    NotificationDeliveryError,
    NotificationDeliveryService,
)
from app.services.notification_digest_service import (
    NotificationDigestError,
    NotificationDigestService,
)

router = APIRouter(tags=["notification-delivery"])

DbSession = Annotated[Session, Depends(get_db)]
DeliverySvc = Annotated[NotificationDeliveryService, Depends(get_notification_delivery_service)]
DigestSvc = Annotated[NotificationDigestService, Depends(get_notification_digest_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except (NotificationDeliveryError, NotificationDigestError) as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class ChannelsRequest(BaseModel):
    """Каналы доставки (email/telegram/webhook/digest)."""

    channels: list[str] = ["email"]


class DigestRequest(BaseModel):
    """Параметры дайджеста."""

    frequency: str = "daily"
    project_id: int | None = None


class SchedulerRequest(BaseModel):
    """Параметры планировщика дайджестов."""

    frequency: str = "daily"


# --- Доставка ---


@router.get("/notification-delivery/logs")
def list_logs(
    db: DbSession,
    service: DeliverySvc,
    user: CurrentUser,
    status_filter: str | None = None,
    channel: str | None = None,
    provider: str | None = None,
    project_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Логи доставки текущего пользователя (фильтры статус/канал/провайдер/проект)."""
    return service.list_user_delivery_logs(
        db,
        user.id,
        status=status_filter,
        channel=channel,
        provider=provider,
        project_id=project_id,
        limit=limit,
    )


@router.get(
    "/notification-delivery/projects/{project_id}/dashboard",
    dependencies=[Depends(require_project_access)],
)
def delivery_dashboard(project_id: int, db: DbSession, service: DeliverySvc) -> dict[str, Any]:
    """Сводка доставки проекта (по статусу/каналу/провайдеру)."""
    return service.build_delivery_dashboard(db, project_id=project_id)


@router.post("/notification-delivery/notifications/{notification_id}/preview")
def preview_delivery(
    notification_id: int,
    payload: ChannelsRequest,
    db: DbSession,
    service: DeliverySvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Предпросмотр доставки по каналам (без записи; masked destination)."""
    return _run(
        lambda: {
            "notification_id": notification_id,
            "previews": [
                service.preview_delivery(db, notification_id, ch, current_user_id=user.id)
                for ch in payload.channels
            ],
        }
    )


@router.post("/notification-delivery/notifications/{notification_id}/send-dry")
def send_dry(
    notification_id: int,
    payload: ChannelsRequest,
    db: DbSession,
    service: DeliverySvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Dry-run доставки: создаёт delivery-задачи и помечает skipped (без внешней отправки)."""
    return _run(
        lambda: service.send_notification(
            db, notification_id, channels=payload.channels, dry_run=True, current_user_id=user.id
        )
    )


@router.post("/notification-delivery/logs/{delivery_log_id}/retry-dry")
def retry_dry(
    delivery_log_id: int, db: DbSession, service: DeliverySvc, user: CurrentUser
) -> dict[str, Any]:
    """Dry-run повторной доставки одной записи (без внешней отправки)."""
    return _run(lambda: service.send_delivery(db, delivery_log_id, dry_run=True))


@router.post("/notification-delivery/logs/{delivery_log_id}/send")
def send_real(
    delivery_log_id: int, db: DbSession, service: DeliverySvc, user: CurrentUser
) -> dict[str, Any]:
    """Реальная отправка одной записи. ОТКАЗ, пока внешняя доставка выключена (по умолчанию)."""
    settings = service._resolve_settings()  # noqa: SLF001 — читаем безопасный флаг
    if not settings.notification_external_delivery_enabled_effective:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Внешняя доставка выключена (NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false)",
        )
    return _run(lambda: service.send_delivery(db, delivery_log_id, dry_run=False))


# --- Дайджесты ---


@router.get("/notification-digests")
def list_digests(db: DbSession, service: DigestSvc, user: CurrentUser) -> list[dict[str, Any]]:
    """Дайджесты текущего пользователя."""
    from app.repositories import notification_delivery_repository as repo

    rows = repo.list_digests_for_user(db, user.id)
    return [
        {
            "id": d.id,
            "frequency": d.frequency,
            "status": d.status,
            "subject": d.subject,
            "notification_count": len(d.notification_ids or []),
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in rows
    ]


@router.post("/notification-digests/preview")
def preview_digest(
    payload: DigestRequest, db: DbSession, service: DigestSvc, user: CurrentUser
) -> dict[str, Any]:
    """Предпросмотр дайджеста (без записи)."""
    return _run(
        lambda: service.preview_digest(
            db,
            user.id,
            frequency=payload.frequency,
            project_id=payload.project_id,
            current_user_id=user.id,
        )
    )


@router.post("/notification-digests/generate-dry")
def generate_digest_dry(
    payload: DigestRequest, db: DbSession, service: DigestSvc, user: CurrentUser
) -> dict[str, Any]:
    """Dry-run генерации дайджеста (без записи)."""
    return _run(
        lambda: service.generate_digest(
            db,
            user.id,
            frequency=payload.frequency,
            project_id=payload.project_id,
            dry_run=True,
            current_user_id=user.id,
        )
    )


@router.post("/notification-digests/generate")
def generate_digest(
    payload: DigestRequest, db: DbSession, service: DigestSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сгенерировать дайджест (только если дайджесты включены; иначе — no-op)."""
    settings = service._resolve_settings()  # noqa: SLF001 — читаем безопасный флаг
    if not settings.notification_digest_enabled_effective:
        return {"digest_id": None, "disabled": True, "message": "Дайджесты выключены"}
    return _run(
        lambda: service.generate_digest(
            db,
            user.id,
            frequency=payload.frequency,
            project_id=payload.project_id,
            dry_run=False,
            current_user_id=user.id,
        )
    )


@router.post("/notification-digests/{digest_id}/send-dry")
def send_digest_dry(
    digest_id: int, db: DbSession, service: DigestSvc, user: CurrentUser
) -> dict[str, Any]:
    """Dry-run отправки дайджеста (без внешней доставки)."""
    return _run(lambda: service.send_digest(db, digest_id, dry_run=True, current_user_id=user.id))


@router.post("/notification-digests/scheduler-dry")
def scheduler_dry(
    payload: SchedulerRequest, db: DbSession, service: DigestSvc, user: CurrentUser
) -> dict[str, Any]:
    """Dry-run планировщика дайджестов (без записи/отправки)."""
    return _run(lambda: service.run_digest_scheduler(db, frequency=payload.frequency, dry_run=True))
