"""REST API Telegram-канала уведомлений: bindings, preview, dry-run (v0.5.4).

Всё — sandbox: реальной Telegram-доставки нет. Пользователь управляет СВОИМИ привязками; проектный
дашборд — под project-гардом. В ответах нет сырого chat_id / verification token / bot token
(verification token отдаётся ТОЛЬКО в момент создания привязки).
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
    get_notification_telegram_binding_service,
    get_telegram_notification_template_service,
)
from app.api.security_guards import require_project_access
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import notification_delivery_repository as delivery_repo
from app.repositories import notification_telegram_repository as telegram_repo
from app.services import audit_log_service as audit_actions
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
    TelegramBindingError,
)
from app.services.telegram_notification_template_service import (
    TelegramNotificationTemplateService,
    TelegramTemplateError,
)

router = APIRouter(prefix="/notification-telegram", tags=["notification-telegram"])

DbSession = Annotated[Session, Depends(get_db)]
BindingSvc = Annotated[
    NotificationTelegramBindingService, Depends(get_notification_telegram_binding_service)
]
TplSvc = Annotated[
    TelegramNotificationTemplateService, Depends(get_telegram_notification_template_service)
]
DeliverySvc = Annotated[NotificationDeliveryService, Depends(get_notification_delivery_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except (TelegramBindingError, TelegramTemplateError) as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class CreateBindingRequest(BaseModel):
    """Создание verification-токена привязки."""

    account_id: int | None = None
    project_id: int | None = None
    title: str | None = None


class VerifyBindingRequest(BaseModel):
    """Ручная верификация привязки (в MVP; в проде — из Telegram webhook/polling)."""

    token: str
    chat_id: str
    telegram_user_id: str | None = None
    username: str | None = None


class VerifyUpdateRequest(BaseModel):
    """Верификация из Telegram update payload (dry-run/локально; без сети)."""

    update: dict[str, Any]


class TelegramPreviewRequest(BaseModel):
    """Preview Telegram-текста для уведомления."""

    template_type: str | None = None


class TestSendRequest(BaseModel):
    """Тестовая Telegram-отправка (dry-run only)."""

    template_type: str = "system_notice"


# --- Bindings ---


@router.get("/bindings")
def list_bindings(db: DbSession, service: BindingSvc, user: CurrentUser) -> list[dict[str, Any]]:
    """Список СВОИХ привязок Telegram (public view, без сырого chat_id/токена)."""
    return service.list_bindings(db, user_id=user.id)


@router.post("/bindings")
def create_binding(
    payload: CreateBindingRequest, db: DbSession, service: BindingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Создать привязку и вернуть verification token (показывается ОДИН раз)."""
    return _run(
        lambda: service.create_binding_token(
            db,
            user.id,
            account_id=payload.account_id,
            project_id=payload.project_id,
            title=payload.title,
            current_user_id=user.id,
        )
    )


@router.post("/bindings/verify")
def verify_binding(
    payload: VerifyBindingRequest, db: DbSession, service: BindingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Верифицировать привязку по token + chat_id (в MVP — вручную)."""
    return _run(
        lambda: service.verify_binding_token(
            db,
            payload.token,
            payload.chat_id,
            telegram_user_id=payload.telegram_user_id,
            username=payload.username,
        )
    )


@router.post("/bindings/verify-update")
def verify_binding_update(
    payload: VerifyUpdateRequest, db: DbSession, service: BindingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Верификация из Telegram update payload (dry-run/локально; реального вызова наружу нет)."""
    return _run(lambda: service.verify_binding_from_update(db, payload.update))


@router.post("/bindings/{binding_id}/disable")
def disable_binding(
    binding_id: int, db: DbSession, service: BindingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отключить СВОЮ привязку."""
    return _run(lambda: service.disable_binding(db, binding_id, current_user_id=user.id))


@router.post("/bindings/{binding_id}/revoke")
def revoke_binding(
    binding_id: int, db: DbSession, service: BindingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отозвать СВОЮ привязку (chat_id обнуляется)."""
    return _run(lambda: service.revoke_binding(db, binding_id, current_user_id=user.id))


# --- Preview / dry-run ---


@router.post("/notifications/{notification_id}/preview")
def preview_notification(
    notification_id: int,
    payload: TelegramPreviewRequest,
    db: DbSession,
    service: TplSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Preview короткого Telegram-текста для СВОЕГО уведомления."""
    return _run(
        lambda: service.render_notification_telegram(
            db, notification_id, template_type=payload.template_type, current_user_id=user.id
        )
    )


@router.post("/notifications/{notification_id}/send-dry")
def send_notification_dry(
    notification_id: int,
    db: DbSession,
    delivery: DeliverySvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать telegram delivery-задачу и «отправить» в DRY-RUN (никакой сети/реальной отправки)."""

    def _do() -> dict[str, Any]:
        log = delivery.create_delivery_job(db, notification_id, "telegram", current_user_id=user.id)
        result = delivery.send_delivery(db, log.id, dry_run=True)
        return {"delivery_log_id": log.id, **result}

    try:
        return _do()
    except Exception as exc:  # noqa: BLE001 — единый безопасный маппинг ошибок доставки
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/test-send-dry")
def test_send_dry(
    payload: TestSendRequest,
    db: DbSession,
    tpl: TplSvc,
    binding_service: BindingSvc,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Тестовый рендер Telegram-сообщения (DRY-RUN only). Реальной отправки нет."""
    binding = binding_service.get_active_binding(db, user.id)
    destination_masked = binding.chat_id_masked if binding is not None else "—"
    preview = tpl.preview_template(payload.template_type, {"user_name": user.full_name or "Тест"})
    if not settings.notification_telegram_test_send_enabled_effective:
        tpl._write_audit(  # noqa: SLF001 — аудит блокировки без сущности
            db,
            audit_actions.ACTION_TELEGRAM_TEST_SEND_BLOCKED,
            user_id=user.id,
            metadata={
                "reason": "telegram_test_send_disabled",
                "template_type": payload.template_type,
            },
        )
        return {
            "would_send": False,
            "blocked": True,
            "reason": "Тестовая отправка выключена (NOTIFICATION_TELEGRAM_TEST_SEND_ENABLED=false)",
            "has_verified_binding": binding is not None,
            "destination_masked": destination_masked,
            "subject": preview["subject"],
        }
    tpl._write_audit(  # noqa: SLF001
        db,
        audit_actions.ACTION_TELEGRAM_TEST_SEND_PREVIEWED,
        user_id=user.id,
        metadata={"template_type": payload.template_type},
    )
    return {
        "would_send": False,
        "dry_run": True,
        "has_verified_binding": binding is not None,
        "destination_masked": destination_masked,
        "subject": preview["subject"],
        "text": preview["text"],
        "parse_mode": preview["parse_mode"],
        "note": "Реальной Telegram-отправки нет; это dry-run/sandbox.",
    }


# --- Project dashboard ---


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def project_dashboard(project_id: int, db: DbSession, settings: SettingsDep) -> dict[str, Any]:
    """Сводка Telegram-канала проекта: привязки, статусы, недавние delivery-логи, live-флаги."""
    bindings = telegram_repo.list_bindings_for_project(db, project_id)
    logs = delivery_repo.list_delivery_logs_for_project(db, project_id, limit=200)
    telegram_logs = [log for log in logs if log.channel == "telegram"][:20]
    return {
        "project_id": project_id,
        "bindings_total": len(bindings),
        "bindings_verified": sum(1 for b in bindings if b.status == "verified"),
        "bindings_disabled": sum(1 for b in bindings if b.status in ("disabled", "revoked")),
        "bindings": [telegram_repo.public_binding_view(b) for b in bindings[:20]],
        "recent_delivery_logs": [
            {
                "id": log.id,
                "status": log.status,
                "provider": log.provider,
                "destination_masked": log.destination_masked,
                "subject": log.subject,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in telegram_logs
        ],
        "flags": {
            "templates_enabled": settings.notification_telegram_templates_enabled_effective,
            "binding_enabled": settings.notification_telegram_binding_enabled_effective,
            "test_send_enabled": settings.notification_telegram_test_send_enabled_effective,
            "live_send_enabled": settings.notification_telegram_live_send_enabled_effective,
            "telegram_live_enabled": settings.notification_telegram_enabled_effective,
            "external_delivery_enabled": settings.notification_external_delivery_enabled_effective,
            "configured": settings.notification_telegram_configured,
            "require_verified_binding": settings.notification_telegram_require_verified_binding,
        },
    }
