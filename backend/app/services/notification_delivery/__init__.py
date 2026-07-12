"""Провайдеры доставки уведомлений (v0.5.1).

Реестр выбирает провайдера по каналу: mock по умолчанию; live-провайдер — ТОЛЬКО если канал
реально включён (external delivery + channel live), что по умолчанию false. Mock-провайдеры не
ходят в сеть; live-провайдеры — skeleton (отказ по флагам, реальной отправки в MVP нет).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.notification_delivery.mock_email_provider import MockEmailProvider
from app.services.notification_delivery.mock_telegram_provider import MockTelegramProvider
from app.services.notification_delivery.mock_webhook_provider import MockWebhookProvider
from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
    mask_destination,
    sanitize_error,
)
from app.services.notification_delivery.smtp_email_provider import SmtpEmailProvider
from app.services.notification_delivery.telegram_notification_provider import (
    TelegramNotificationProvider,
)
from app.services.notification_delivery.webhook_notification_provider import (
    WebhookNotificationProvider,
)

if TYPE_CHECKING:
    from app.config import Settings

__all__ = [
    "MockEmailProvider",
    "MockTelegramProvider",
    "MockWebhookProvider",
    "NotificationDeliveryProvider",
    "NotificationDeliveryProviderRegistry",
    "NotificationDeliveryRequest",
    "NotificationDeliveryResult",
    "SmtpEmailProvider",
    "TelegramNotificationProvider",
    "WebhookNotificationProvider",
    "mask_destination",
    "sanitize_error",
]


class NotificationDeliveryProviderRegistry:
    """Выбор провайдера по каналу: live только когда канал реально включён; иначе mock."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings
        self._mocks: dict[str, NotificationDeliveryProvider] = {
            "email": MockEmailProvider(),
            "telegram": MockTelegramProvider(),
            "webhook": MockWebhookProvider(),
            "digest": MockEmailProvider(),  # дайджест доставляется как email
        }

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def resolve(self, channel: str) -> NotificationDeliveryProvider:
        """Вернуть провайдера канала: live только при включённом канале, иначе mock (sandbox)."""
        settings = self._resolve_settings()
        if channel == "email" and (
            settings.notification_email_enabled_effective
            and settings.notification_email_provider == "smtp"
        ):
            return SmtpEmailProvider(settings)
        if channel == "telegram" and (
            settings.notification_telegram_enabled_effective
            and settings.notification_telegram_provider == "telegram_bot"
        ):
            return TelegramNotificationProvider(settings)
        if channel == "webhook" and (
            settings.notification_webhook_enabled_effective
            and settings.notification_webhook_provider == "webhook"
        ):
            return WebhookNotificationProvider(settings)
        return self._mocks.get(channel, self._mocks["email"])
