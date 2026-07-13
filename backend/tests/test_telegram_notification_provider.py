"""Тесты Telegram-провайдеров (v0.5.4). Offline; без сети; отправитель внедряется.

Гарантии: mock не ходит в сеть; live-провайдер ОТКАЗЫВАЕТ по умолчанию; live-путь достижим только
при всех флагах и использует внедрённый http_sender (сети нет); bot token не утекает в результат.
"""

from typing import Any

from app.config import Settings
from app.services.notification_delivery import NotificationDeliveryRequest
from app.services.notification_delivery.mock_telegram_provider import MockTelegramProvider
from app.services.notification_delivery.telegram_notification_provider import (
    TelegramNotificationProvider,
)


def _request(**kw: Any) -> NotificationDeliveryRequest:
    base: dict[str, Any] = {
        "provider": "telegram_bot",
        "channel": "telegram",
        "recipient_user_id": 1,
        "destination": "123456789",
        "subject": "Тема",
        "message": "Тело сообщения",
    }
    base.update(kw)
    return NotificationDeliveryRequest(**base)


def _live_settings() -> Settings:
    """Настройки, проходящие ВСЕ гейты Telegram live (для проверки live-пути с фейковым sender)."""
    return Settings(
        notifications_enabled=True,
        notification_delivery_enabled=True,
        notification_external_delivery_enabled=True,
        notification_telegram_enabled=True,
        notification_telegram_live_enabled=True,
        notification_telegram_live_send_enabled=True,
        notification_telegram_bot_token="999999:SECRETtokenABCDEFGHIJKLMNOP",
    )


def test_mock_no_network_sandbox() -> None:
    result = MockTelegramProvider().send(_request())
    assert result.ok is True
    assert result.status == "sent"
    assert result.provider_message_id.startswith("mock_telegram_")
    assert result.response_metadata["delivered"] is False
    assert result.response_metadata["sandbox"] is True
    assert "would_send_text_preview" in result.response_metadata


def test_mock_destination_masked() -> None:
    result = MockTelegramProvider().send(_request(destination="987654321"))
    assert "987654321" not in result.destination_masked
    assert "***" in result.destination_masked


def test_live_refuses_when_external_disabled() -> None:
    result = TelegramNotificationProvider(Settings()).send(_request())
    assert result.status == "disabled"
    assert result.ok is False


def test_live_refuses_when_telegram_live_send_false() -> None:
    settings = _live_settings()
    settings.notification_telegram_live_send_enabled = False
    result = TelegramNotificationProvider(settings).send(_request())
    assert result.status == "disabled"


def test_blocked_reason_progression() -> None:
    provider = TelegramNotificationProvider(Settings())
    assert provider._blocked_reason(Settings()) is not None
    assert provider._blocked_reason(_live_settings()) is None


def test_live_path_uses_injected_sender_no_network() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def sender(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        calls.append((url, payload))
        return {"ok": True, "result": {"message_id": 42}}

    provider = TelegramNotificationProvider(_live_settings(), http_sender=sender)
    result = provider.send(_request())
    assert result.ok is True
    assert result.status == "sent"
    assert result.provider_message_id == "tg-42"
    assert calls[0][1]["chat_id"] == "123456789"


def test_bot_token_not_in_result_or_error() -> None:
    settings = _live_settings()

    def boom(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        raise RuntimeError(f"connect failed with token {settings.notification_telegram_bot_token}")

    result = TelegramNotificationProvider(settings, http_sender=boom).send(_request())
    assert result.ok is False
    assert result.status == "failed"
    assert settings.notification_telegram_bot_token not in (result.error_message or "")
    # URL с токеном тоже не утекает.
    assert "999999:SECRET" not in str(result.response_metadata)


def test_destination_masked_in_live_result() -> None:
    def sender(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        return {"ok": True, "result": {"message_id": 7}}

    result = TelegramNotificationProvider(_live_settings(), http_sender=sender).send(
        _request(destination="55554444")
    )
    assert "55554444" not in (result.destination_masked or "")
    assert "***" in (result.destination_masked or "")
