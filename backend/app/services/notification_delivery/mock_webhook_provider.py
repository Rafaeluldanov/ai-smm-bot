"""Mock webhook-провайдер — v0.5.1. Пишет результат доставки, но НИКОГДА не ходит в сеть."""

from __future__ import annotations

from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
)


class MockWebhookProvider(NotificationDeliveryProvider):
    """Sandbox webhook: имитирует успешную доставку без реального HTTP-вызова."""

    provider_name = "mock"
    channel = "webhook"

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Вернуть mock-«sent» результат (реальный HTTP POST не выполняется)."""
        return NotificationDeliveryResult(
            ok=True,
            status="sent",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            provider_message_id=self._mock_message_id(request),
            response_metadata={"delivered": False, "sandbox": True},
        )
