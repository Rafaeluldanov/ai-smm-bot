"""REST API safety-слоя уведомлений (v0.5.2): opt-out, suppression, rate-limit, webhooks.

Пользователь управляет СВОИМИ отписками/подавлениями/лимитами; webhook-подписки — в пределах
доступного аккаунта/проекта. Публичная страница отписки работает по подписанному токену (без
auth). Сырые URL/секреты наружу НЕ отдаются; реальной внешней доставки нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_db,
    get_notification_rate_limit_service,
    get_notification_suppression_service,
    get_notification_unsubscribe_service,
    get_optional_user,
    get_webhook_subscription_service,
)
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import notification_safety_repository as safety_repo
from app.services import saas_security_service as security
from app.services.notification_rate_limit_service import NotificationRateLimitService
from app.services.notification_suppression_service import (
    NotificationSuppressionError,
    NotificationSuppressionService,
)
from app.services.notification_unsubscribe_service import (
    NotificationUnsubscribeError,
    NotificationUnsubscribeService,
)
from app.services.webhook_subscription_service import (
    WebhookSubscriptionError,
    WebhookSubscriptionService,
)

router = APIRouter(tags=["notification-safety"])

DbSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
OptUser = Annotated[User | None, Depends(get_optional_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
UnsubSvc = Annotated[NotificationUnsubscribeService, Depends(get_notification_unsubscribe_service)]
RateSvc = Annotated[NotificationRateLimitService, Depends(get_notification_rate_limit_service)]
SuppSvc = Annotated[NotificationSuppressionService, Depends(get_notification_suppression_service)]
WebhookSvc = Annotated[WebhookSubscriptionService, Depends(get_webhook_subscription_service)]

_T = TypeVar("_T")
_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except (
        NotificationUnsubscribeError,
        NotificationSuppressionError,
        WebhookSubscriptionError,
    ) as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _guard_account(db: Session, settings: Settings, user: User | None, account_id: int) -> None:
    """Проверить доступ пользователя к аккаунту (dev-анонимно допускается вне production)."""
    if user is None:
        if settings.is_production or settings.security_require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация"
            )
        return
    if not security.user_can_access_account(db, user, account_id):
        raise _NOT_FOUND


# --- Запросы ---


class OptOutRequest(BaseModel):
    """Создание отписки."""

    scope: str = "global"
    channel: str | None = None
    notification_type: str | None = None
    project_id: int | None = None
    reason: str | None = None


class RateCheckRequest(BaseModel):
    """Проверка лимита канала."""

    channel: str = "email"
    project_id: int | None = None


class WebhookCreateRequest(BaseModel):
    """Создание webhook-подписки."""

    account_id: int
    title: str = "webhook"
    url: str
    event_types: list[str] | None = None
    project_id: int | None = None
    signing_secret: str | None = None


class WebhookUpdateRequest(BaseModel):
    """Обновление webhook-подписки."""

    title: str | None = None
    status: str | None = None
    event_types: list[str] | None = None
    url: str | None = None
    signing_secret: str | None = None


class UnsubscribeRequest(BaseModel):
    """Отписка по токену."""

    token: str
    reason: str | None = None


# --- Opt-out (user-scoped) ---


@router.get("/notification-safety/opt-outs")
def list_opt_outs(db: DbSession, service: UnsubSvc, user: CurrentUser) -> list[dict[str, Any]]:
    """Отписки текущего пользователя."""
    return service.list_opt_outs(db, user.id)


@router.post("/notification-safety/opt-outs")
def create_opt_out(
    payload: OptOutRequest, db: DbSession, service: UnsubSvc, user: CurrentUser
) -> dict[str, Any]:
    """Создать отписку для текущего пользователя."""
    return _run(
        lambda: service.create_opt_out(
            db,
            user.id,
            payload.scope,
            channel=payload.channel,
            project_id=payload.project_id,
            notification_type=payload.notification_type,
            reason=payload.reason,
            current_user_id=user.id,
        )
    )


@router.post("/notification-safety/opt-outs/{opt_out_id}/revoke")
def revoke_opt_out(
    opt_out_id: int, db: DbSession, service: UnsubSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отменить отписку (только владелец)."""
    return _run(lambda: service.revoke_opt_out(db, opt_out_id, current_user_id=user.id))


# --- Suppression (user-scoped) ---


@router.get("/notification-safety/suppressions")
def list_suppressions(
    db: DbSession, service: SuppSvc, user: CurrentUser, status_filter: str | None = None
) -> list[dict[str, Any]]:
    """Подавления текущего пользователя."""
    return service.list_suppressions(db, user_id=user.id, status=status_filter)


@router.post("/notification-safety/suppressions/{suppression_id}/clear")
def clear_suppression(
    suppression_id: int, db: DbSession, service: SuppSvc, user: CurrentUser
) -> dict[str, Any]:
    """Снять подавление (только владелец)."""
    return _run(lambda: service.clear_suppression(db, suppression_id, current_user_id=user.id))


# --- Rate limits (user-scoped) ---


@router.get("/notification-safety/rate-limits")
def rate_limits(db: DbSession, service: RateSvc, user: CurrentUser) -> dict[str, Any]:
    """Сводка лимитов доставки текущего пользователя."""
    return service.build_rate_limit_dashboard(db, user_id=user.id)


@router.post("/notification-safety/rate-limits/check")
def rate_limit_check(
    payload: RateCheckRequest, db: DbSession, service: RateSvc, user: CurrentUser
) -> dict[str, Any]:
    """Проверить лимит канала для текущего пользователя (без инкремента)."""
    return service.check_delivery_allowed(
        db, user.id, payload.channel, project_id=payload.project_id
    )


# --- Webhook subscriptions (account-scoped) ---


@router.get("/notification-safety/webhooks")
def list_webhooks(
    db: DbSession,
    service: WebhookSvc,
    user: OptUser,
    settings: SettingsDep,
    account_id: int,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    """Webhook-подписки аккаунта (доступ к аккаунту обязателен)."""
    _guard_account(db, settings, user, account_id)
    return service.list_subscriptions(db, account_id=account_id, project_id=project_id)


@router.post("/notification-safety/webhooks")
def create_webhook(
    payload: WebhookCreateRequest,
    db: DbSession,
    service: WebhookSvc,
    user: OptUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Создать webhook-подписку (URL/secret шифруются; наружу только masked)."""
    _guard_account(db, settings, user, payload.account_id)
    return _run(
        lambda: service.create_subscription(
            db,
            payload.account_id,
            payload.title,
            payload.url,
            event_types=payload.event_types,
            project_id=payload.project_id,
            user_id=user.id if user is not None else None,
            signing_secret=payload.signing_secret,
        )
    )


def _guard_webhook(db: Session, settings: Settings, user: User | None, subscription_id: int) -> Any:
    sub = safety_repo.get_webhook_subscription_by_id(db, subscription_id)
    if sub is None:
        raise _NOT_FOUND
    _guard_account(db, settings, user, sub.account_id)
    return sub


@router.get("/notification-safety/webhooks/{subscription_id}")
def get_webhook(
    subscription_id: int, db: DbSession, service: WebhookSvc, user: OptUser, settings: SettingsDep
) -> dict[str, Any]:
    """Одна webhook-подписка (masked)."""
    _guard_webhook(db, settings, user, subscription_id)
    return _run(lambda: service.get_subscription(db, subscription_id))


@router.patch("/notification-safety/webhooks/{subscription_id}")
def update_webhook(
    subscription_id: int,
    payload: WebhookUpdateRequest,
    db: DbSession,
    service: WebhookSvc,
    user: OptUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Обновить webhook-подписку."""
    _guard_webhook(db, settings, user, subscription_id)
    return _run(
        lambda: service.update_subscription(
            db,
            subscription_id,
            title=payload.title,
            status=payload.status,
            event_types=payload.event_types,
            url=payload.url,
            signing_secret=payload.signing_secret,
        )
    )


@router.post("/notification-safety/webhooks/{subscription_id}/revoke")
def revoke_webhook(
    subscription_id: int, db: DbSession, service: WebhookSvc, user: OptUser, settings: SettingsDep
) -> dict[str, Any]:
    """Отозвать webhook-подписку."""
    _guard_webhook(db, settings, user, subscription_id)
    return _run(
        lambda: service.revoke_subscription(
            db, subscription_id, current_user_id=user.id if user is not None else None
        )
    )


@router.post("/notification-safety/webhooks/{subscription_id}/preview")
def preview_webhook(
    subscription_id: int,
    db: DbSession,
    service: WebhookSvc,
    user: OptUser,
    settings: SettingsDep,
    notification_id: int | None = None,
) -> dict[str, Any]:
    """Показать подписанный payload webhook (без реальной отправки)."""
    _guard_webhook(db, settings, user, subscription_id)
    return _run(lambda: service.preview_webhook_delivery(db, subscription_id, notification_id))


# --- Публичная отписка (по токену, без auth) ---


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_page(token: str, db: DbSession, service: UnsubSvc) -> HTMLResponse:
    """Публичная страница отписки: проверка токена (без создания opt-out на GET)."""
    payload = service.verify_unsubscribe_token(token)
    if payload is None:
        return HTMLResponse(
            "<h2>Отписка</h2><p>Ссылка недействительна или устарела.</p>", status_code=400
        )
    import html as _html

    scope = _html.escape(str(payload.get("scope", "global")))
    safe_token = _html.escape(token)
    body = (
        "<h2>Отписка от уведомлений</h2>"
        f"<p>Область: <b>{scope}</b>. Нажмите, чтобы подтвердить отписку.</p>"
        "<script>async function unsub(){await fetch('/unsubscribe',{method:'POST',"
        "headers:{'Content-Type':'application/json'},"
        f"body:JSON.stringify({{token:'{safe_token}'}})}});"
        "document.getElementById('u-msg').textContent='Вы отписаны.';}</script>"
        "<button onclick='unsub()'>Отписаться</button><p id='u-msg'></p>"
        "<p><small>Внешняя доставка выключена — это управление подпиской на будущее.</small></p>"
    )
    return HTMLResponse(body)


@router.post("/unsubscribe")
def unsubscribe_confirm(
    payload: UnsubscribeRequest, db: DbSession, service: UnsubSvc
) -> dict[str, Any]:
    """Создать opt-out по токену отписки (публично)."""
    return _run(lambda: service.create_opt_out_from_token(db, payload.token, payload.reason))
