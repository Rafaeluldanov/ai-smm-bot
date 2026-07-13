"""REST API Telegram-канала уведомлений: bindings, preview, webhook/polling sandbox (v0.5.4–v0.5.5).

Всё — sandbox: реальной Telegram-доставки и реальных Telegram API-вызовов нет. Пользователь
управляет СВОИМИ привязками; проектный дашборд — под project-гардом. Webhook-эндпоинт — без auth,
но с настраиваемой secret-проверкой. В ответах нет сырого chat_id / verification token / bot token.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_db,
    get_notification_delivery_service,
    get_notification_telegram_binding_service,
    get_telegram_bot_management_service,
    get_telegram_incoming_service,
    get_telegram_notification_template_service,
)
from app.api.security_guards import require_project_access
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import notification_delivery_repository as delivery_repo
from app.repositories import notification_telegram_repository as telegram_repo
from app.repositories import notification_telegram_update_repository as update_repo
from app.services import audit_log_service as audit_actions
from app.services.notification_delivery_service import NotificationDeliveryService
from app.services.notification_telegram_binding_service import (
    NotificationTelegramBindingService,
    TelegramBindingError,
)
from app.services.telegram_bot_management_service import TelegramBotManagementService
from app.services.telegram_incoming_service import TelegramIncomingService
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
IncomingSvc = Annotated[TelegramIncomingService, Depends(get_telegram_incoming_service)]
BotMgmtSvc = Annotated[TelegramBotManagementService, Depends(get_telegram_bot_management_service)]
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


# ======================================================================= #
# Webhook / polling sandbox (v0.5.5)                                       #
# ======================================================================= #


class SimulateUpdateRequest(BaseModel):
    """Симуляция входящего ``/start``-апдейта (sandbox)."""

    token: str
    chat_id: str
    telegram_user_id: str | None = None
    username: str | None = None
    update_id: int | None = None


class WebhookSetDryRequest(BaseModel):
    """DRY-RUN setWebhook (без сети)."""

    url: str | None = None


class PollingDryRequest(BaseModel):
    """DRY-RUN getUpdates (без сети)."""

    offset: int | None = None
    limit: int | None = None


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    incoming: IncomingSvc,
    db: DbSession,
    x_telegram_bot_api_secret_token: Annotated[
        str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")
    ] = None,
) -> dict[str, Any]:
    """Incoming Telegram webhook (БЕЗ auth). Проверяет secret-заголовок, парсит, логирует.

    Ответных сообщений наружу НЕ отправляет. Всегда возвращает 200 (кроме invalid_secret → 403),
    чтобы Telegram не ретраил бесконечно. Секреты/сырой chat_id наружу не отдаются.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 — некорректный JSON не должен 500-ить вебхук
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    request_ip = request.client.host if request.client else None
    result = incoming.handle_webhook_update(
        db,
        payload,
        secret_header=x_telegram_bot_api_secret_token,
        request_ip=request_ip,
    )
    if result.get("status") == "invalid_secret":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid secret token")
    return result


@router.post("/simulate-update")
def simulate_update(
    payload: SimulateUpdateRequest, db: DbSession, incoming: IncomingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Симулировать входящий ``/start``-апдейт (dry/sandbox; только для авторизованного юзера)."""
    return incoming.simulate_update(
        db,
        payload.token,
        payload.chat_id,
        telegram_user_id=payload.telegram_user_id,
        username=payload.username,
        update_id=payload.update_id,
    )


@router.get("/updates")
def list_updates(db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """Недавние входящие апдейты пользователя (public view, без сырого chat_id/токена)."""
    return [update_repo.public_update_view(x) for x in update_repo.list_for_user(db, user.id)]


@router.get("/projects/{project_id}/updates", dependencies=[Depends(require_project_access)])
def list_project_updates(project_id: int, db: DbSession) -> list[dict[str, Any]]:
    """Входящие апдейты проекта (public view)."""
    return [update_repo.public_update_view(x) for x in update_repo.list_for_project(db, project_id)]


@router.get("/webhook-dashboard")
def webhook_dashboard(db: DbSession, incoming: IncomingSvc, user: CurrentUser) -> dict[str, Any]:
    """Сводка webhook-канала пользователя: недавние апдейты, счётчики, URL, live-флаги, secret."""
    return incoming.build_webhook_dashboard(db, user_id=user.id)


@router.get(
    "/projects/{project_id}/webhook-dashboard",
    dependencies=[Depends(require_project_access)],
)
def project_webhook_dashboard(
    project_id: int, db: DbSession, incoming: IncomingSvc
) -> dict[str, Any]:
    """Сводка webhook-канала проекта."""
    return incoming.build_webhook_dashboard(db, project_id=project_id)


@router.post("/webhook/set-dry")
def webhook_set_dry(
    payload: WebhookSetDryRequest,
    db: DbSession,
    manager: BotMgmtSvc,
    tpl: TplSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """DRY-RUN setWebhook (без сети): показывает payload, который был бы отправлен."""
    tpl._write_audit(  # noqa: SLF001 — аудит dry-run без сущности
        db, audit_actions.ACTION_TELEGRAM_WEBHOOK_SET_DRY, user_id=user.id, metadata={}
    )
    return manager.set_webhook_dry(url=payload.url)


@router.post("/webhook/delete-dry")
def webhook_delete_dry(manager: BotMgmtSvc, user: CurrentUser) -> dict[str, Any]:
    """DRY-RUN deleteWebhook (без сети)."""
    return manager.delete_webhook_dry()


@router.get("/webhook/info-dry")
def webhook_info_dry(
    db: DbSession, manager: BotMgmtSvc, tpl: TplSvc, user: CurrentUser
) -> dict[str, Any]:
    """DRY-RUN getWebhookInfo (без сети)."""
    tpl._write_audit(  # noqa: SLF001
        db, audit_actions.ACTION_TELEGRAM_WEBHOOK_INFO_DRY, user_id=user.id, metadata={}
    )
    return manager.get_webhook_info_dry()


@router.post("/polling/dry")
def polling_dry(
    payload: PollingDryRequest,
    db: DbSession,
    manager: BotMgmtSvc,
    tpl: TplSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """DRY-RUN getUpdates (без сети): показывает параметры polling."""
    tpl._write_audit(  # noqa: SLF001
        db, audit_actions.ACTION_TELEGRAM_POLLING_DRY_RUN, user_id=user.id, metadata={}
    )
    return manager.poll_updates_dry(offset=payload.offset, limit=payload.limit)
