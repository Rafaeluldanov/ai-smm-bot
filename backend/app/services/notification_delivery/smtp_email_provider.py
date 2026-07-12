"""SMTP email-провайдер (skeleton) — v0.5.1.

Реальная отправка НЕ реализована в MVP и наружу ничего не идёт. Провайдер отказывается, если
внешняя доставка/email-live выключены (по умолчанию — выключены). Сетевые библиотеки НЕ
импортируются: это защита от случайной реальной отправки.
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


class SmtpEmailProvider(NotificationDeliveryProvider):
    """Live SMTP-провайдер (skeleton): реальная отправка выключена по умолчанию."""

    provider_name = "smtp"
    channel = "email"

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Отказать, если внешняя доставка/email-live выключены; иначе — not implemented."""
        settings = self._resolve_settings()
        if not settings.notification_email_enabled_effective:
            return self._disabled_result(
                request, "external email delivery disabled (NOTIFICATION_EMAIL_LIVE_ENABLED=false)"
            )
        # Реальная SMTP-отправка в MVP НЕ реализована (skeleton) — наружу ничего не идёт.
        return NotificationDeliveryResult(
            ok=False,
            status="failed",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            error_message="live SMTP delivery not implemented in MVP",
            response_metadata={"delivered": False},
        )
