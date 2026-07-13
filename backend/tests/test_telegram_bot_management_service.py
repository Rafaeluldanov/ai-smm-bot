"""Тесты сервиса управления Telegram-ботом (v0.5.5). Offline; dry-run; live за флагами."""

from typing import Any

from app.config import Settings
from app.services.telegram_bot_management_service import TelegramBotManagementService


def _live_settings() -> Settings:
    """Настройки, проходящие ВСЕ гейты management/polling live (для проверки с фейковым sender)."""
    return Settings(
        notifications_enabled=True,
        notification_delivery_enabled=True,
        notification_external_delivery_enabled=True,
        notification_telegram_enabled=True,
        notification_telegram_live_enabled=True,
        notification_telegram_bot_token="999999:SECRETtokenABCDEFGHIJKLMNOP",
        notification_telegram_webhook_management_live_enabled=True,
        notification_telegram_webhook_management_dry_run=False,
        notification_telegram_polling_live_enabled=True,
        notification_telegram_polling_dry_run=False,
    )


def test_webhook_preview_no_call() -> None:
    r = TelegramBotManagementService(settings=Settings()).preview_webhook_setup()
    assert r["would_call_setWebhook"] is False
    assert r["live_enabled"] is False


def test_set_webhook_dry_no_network() -> None:
    r = TelegramBotManagementService(settings=Settings()).set_webhook_dry(url="https://x/wh")
    assert r["dry_run"] is True
    assert r["would_send"]["url"] == "https://x/wh"


def test_get_webhook_info_dry_no_network() -> None:
    r = TelegramBotManagementService(settings=Settings()).get_webhook_info_dry()
    assert r["dry_run"] is True
    assert r["method"] == "getWebhookInfo"


def test_delete_webhook_dry_no_network() -> None:
    r = TelegramBotManagementService(settings=Settings()).delete_webhook_dry()
    assert r["dry_run"] is True
    assert r["method"] == "deleteWebhook"


def test_polling_dry_no_network() -> None:
    r = TelegramBotManagementService(settings=Settings()).poll_updates_dry(limit=10)
    assert r["dry_run"] is True
    assert r["would_send"]["limit"] == 10


def test_set_webhook_live_refuses_without_flags() -> None:
    r = TelegramBotManagementService(settings=Settings()).set_webhook_live(url="https://x")
    assert r["status"] == "disabled"
    assert r["ok"] is False


def test_poll_updates_live_refuses_without_flags() -> None:
    r = TelegramBotManagementService(settings=Settings()).poll_updates_live()
    assert r["status"] == "disabled"
    assert r["ok"] is False


def test_live_works_only_with_all_flags_fake_transport() -> None:
    calls: list[tuple[str, str]] = []

    def sender(method: str, url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        calls.append((method, url))
        return {"ok": True, "result": True}

    r = TelegramBotManagementService(_live_settings(), http_sender=sender).set_webhook_live(
        url="https://x/wh"
    )
    assert r["ok"] is True
    assert r["status"] == "sent"
    assert calls[0][0] == "setWebhook"
    assert "/bot999999" in calls[0][1]


def test_bot_token_not_in_error() -> None:
    settings = _live_settings()

    def boom(method: str, url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        raise RuntimeError(f"connect failed {settings.notification_telegram_bot_token}")

    r = TelegramBotManagementService(settings, http_sender=boom).set_webhook_live(url="https://x")
    assert r["ok"] is False
    assert settings.notification_telegram_bot_token not in r["error"]
    assert "999999:SECRET" not in r["error"]
