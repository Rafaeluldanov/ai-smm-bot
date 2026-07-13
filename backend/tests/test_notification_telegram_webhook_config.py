"""Тесты конфигурации Telegram webhook/polling (v0.5.5). Дефолты безопасны; live выключен."""

from app.config import Settings


def test_webhook_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_webhook_enabled is True
    assert s.notification_telegram_webhook_live_enabled is False
    assert s.notification_telegram_webhook_secret_required is False
    assert s.notification_telegram_webhook_allow_local_without_secret is True


def test_polling_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_polling_enabled is True
    assert s.notification_telegram_polling_live_enabled is False
    assert s.notification_telegram_polling_dry_run is True


def test_management_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_webhook_management_live_enabled is False
    assert s.notification_telegram_webhook_management_dry_run is True


def test_effective_flags_all_off_by_default() -> None:
    s = Settings()
    assert s.notification_telegram_webhook_enabled_effective is True
    assert s.notification_telegram_webhook_live_enabled_effective is False
    assert s.notification_telegram_polling_live_enabled_effective is False
    assert s.notification_telegram_webhook_management_live_enabled_effective is False
    assert s.notification_external_delivery_enabled_effective is False
    assert s.notification_telegram_webhook_secret_required_effective is False


def test_webhook_path_and_url() -> None:
    s = Settings()
    assert s.notification_telegram_webhook_path_effective == "/notification-telegram/webhook"
    # Без public url — только path.
    assert s.notification_telegram_webhook_public_url_effective == "/notification-telegram/webhook"
    s2 = Settings(notification_telegram_webhook_public_url="https://app.example.com/")
    assert (
        s2.notification_telegram_webhook_public_url_effective
        == "https://app.example.com/notification-telegram/webhook"
    )


def test_limits_clamped() -> None:
    assert (
        Settings(notification_telegram_polling_limit=0).notification_telegram_polling_limit_safe
        == 20
    )
    assert (
        Settings(notification_telegram_polling_limit=9999).notification_telegram_polling_limit_safe
        == 100
    )
    assert (
        Settings(
            notification_telegram_incoming_max_text_preview=9999
        ).notification_telegram_incoming_max_text_preview_safe
        == 512
    )


def test_live_requires_all_flags() -> None:
    # Даже при включённом live, без external эффективный флаг остаётся False.
    s = Settings(
        notification_telegram_webhook_live_enabled=True,
        notification_telegram_bot_token="123:ABC",
    )
    assert s.notification_telegram_webhook_live_enabled_effective is False
    s2 = Settings(
        notification_external_delivery_enabled=True,
        notification_telegram_enabled=True,
        notification_telegram_live_enabled=True,
        notification_telegram_webhook_live_enabled=True,
        notification_telegram_bot_token="123:ABCDEF",
    )
    assert s2.notification_telegram_webhook_live_enabled_effective is True
