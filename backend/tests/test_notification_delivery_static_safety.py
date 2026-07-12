"""Статические safety-проверки доставки уведомлений (v0.5.1, Часть 18)."""

import importlib
import inspect

from app.config import Settings
from app.services.notification_delivery import (
    NotificationDeliveryRequest,
    SmtpEmailProvider,
    TelegramNotificationProvider,
    WebhookNotificationProvider,
)

_FORBIDDEN = ("scripts.publish_due", "import publish_due", "publish_due(")
_NETWORK_TOKENS = ("smtplib", "requests.", "httpx.", "urllib.request", "aiosmtp", "socket.")
_MODULES = (
    "app.services.notification_delivery_service",
    "app.services.notification_digest_service",
    "app.services.notification_delivery.provider",
    "app.services.notification_delivery.mock_email_provider",
    "app.services.notification_delivery.smtp_email_provider",
    "app.services.notification_delivery.telegram_notification_provider",
    "app.services.notification_delivery.webhook_notification_provider",
    "app.api.notification_delivery",
    "app.scripts.notification_delivery_preview",
    "app.scripts.notification_delivery_send",
    "app.scripts.notification_delivery_retry",
    "app.scripts.notification_digest_preview",
    "app.scripts.notification_digest_generate",
    "app.scripts.notification_digest_scheduler",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_modules_no_publish_due() -> None:
    for module in _MODULES:
        src = _source(module)
        for token in _FORBIDDEN:
            assert token not in src, f"{token} в {module}"


def test_no_network_libraries_in_delivery() -> None:
    # Ни один провайдер/сервис доставки не импортирует сетевые библиотеки.
    for module in _MODULES:
        src = _source(module).lower()
        for token in _NETWORK_TOKENS:
            assert token not in src, f"{token} в {module}"


def test_live_providers_refuse_without_external_flag() -> None:
    req = NotificationDeliveryRequest(
        provider="smtp",
        channel="email",
        recipient_user_id=1,
        destination="a@b.ru",
        subject="s",
        message="m",
    )
    # По умолчанию external выключен → live-провайдеры отказывают (disabled).
    settings = Settings()
    assert SmtpEmailProvider(settings).send(req).status == "disabled"
    req.channel = "telegram"
    assert TelegramNotificationProvider(settings).send(req).status == "disabled"
    req.channel = "webhook"
    assert WebhookNotificationProvider(settings).send(req).status == "disabled"


def test_api_no_live_publish() -> None:
    src = _source("app.api.notification_delivery").lower()
    for token in ("publish_due", "wall.post", "telegram_live", "vk_live"):
        assert token not in src


def test_result_view_no_secret_fields() -> None:
    src = _source("app.services.notification_delivery_service")
    view_src = src.split("def _log_view", 1)[1].split("\n    # --- audit", 1)[0]
    for token in ("smtp_password", "bot_token", "signing_secret", "password_hash"):
        assert token not in view_src


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.notification_external_delivery_enabled is False
    assert s.notification_email_live_enabled is False
    assert s.notification_telegram_live_enabled is False
    assert s.notification_webhook_live_enabled is False
    assert s.notification_digest_enabled is False
    assert s.notification_delivery_dry_run is True
    # Никаких live-флагов/платежей.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_billing_delivery_actions_free() -> None:
    from app.services import billing_service

    for usage in (
        billing_service.USAGE_NOTIFICATION_DELIVERY_PREVIEW,
        billing_service.USAGE_NOTIFICATION_DELIVERY_SEND,
        billing_service.USAGE_NOTIFICATION_DIGEST_GENERATE,
        billing_service.USAGE_NOTIFICATION_DIGEST_SEND,
    ):
        assert billing_service.ACTION_COSTS[usage] == 0
