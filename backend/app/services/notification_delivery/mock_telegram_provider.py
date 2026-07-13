"""Mock Telegram-провайдер — v0.5.1/v0.5.4. Пишет результат доставки, но НИКОГДА не ходит в сеть."""

from __future__ import annotations

from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
)


class MockTelegramProvider(NotificationDeliveryProvider):
    """Sandbox Telegram: имитирует успешную доставку без реальной отправки (никакой сети)."""

    provider_name = "mock"
    channel = "telegram"

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Вернуть mock-«sent» результат (реальный Telegram Bot API не вызывается)."""
        preview = (request.message or "")[:120]
        return NotificationDeliveryResult(
            ok=True,
            status="sent",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            provider_message_id=self._mock_message_id(request).replace(
                "mock-telegram-", "mock_telegram_"
            ),
            response_metadata={
                "delivered": False,
                "sandbox": True,
                "would_send_text_preview": preview,
            },
        )
