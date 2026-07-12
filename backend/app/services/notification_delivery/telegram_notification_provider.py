"""Telegram notification-провайдер (skeleton) — v0.5.1.

Реальная отправка НЕ реализована в MVP и наружу ничего не идёт. Отказывается, если внешняя
доставка/telegram-live выключены (по умолчанию). Сетевые библиотеки НЕ импортируются.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
)

if TYPE_CHECKING:
    from app.config import Settings


class TelegramNotificationProvider(NotificationDeliveryProvider):
    """Live Telegram-провайдер (skeleton): реальная отправка выключена по умолчанию."""

    provider_name = "telegram_bot"
    channel = "telegram"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Отказать, если внешняя доставка/telegram-live выключены; иначе — not implemented."""
        settings = self._resolve_settings()
        if not settings.notification_telegram_enabled_effective:
            return self._disabled_result(
                request,
                "external telegram delivery disabled (NOTIFICATION_TELEGRAM_LIVE_ENABLED=false)",
            )
        # Реальная отправка через Telegram Bot API в MVP НЕ реализована (skeleton).
        return NotificationDeliveryResult(
            ok=False,
            status="failed",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            error_message="live telegram delivery not implemented in MVP",
            response_metadata={"delivered": False},
        )
