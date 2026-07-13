"""Тесты конфигурации Telegram-уведомлений (v0.5.4). Дефолты безопасны; live выключен."""

from app.config import Settings


def test_telegram_defaults_safe() -> None:
    s = Settings()
    assert s.notification_telegram_live_send_enabled is False
    assert s.notification_telegram_test_send_enabled is False
    assert s.notification_telegram_test_send_dry_run is True
    assert s.notification_telegram_binding_enabled is True
    assert s.notification_telegram_require_verified_binding is True
    assert s.notification_telegram_allow_unverified_test is False


def test_telegram_effective_flags() -> None:
    s = Settings()
    assert s.notification_telegram_templates_enabled_effective is True
    assert s.notification_telegram_binding_enabled_effective is True
    assert s.notification_telegram_test_send_enabled_effective is False
    assert s.notification_telegram_live_send_enabled_effective is False
    assert s.notification_telegram_configured is False


def test_max_message_chars_clamped() -> None:
    assert (
        Settings(
            notification_telegram_max_message_chars=0
        ).notification_telegram_max_message_chars_safe
        == 3900
    )
    assert (
        Settings(
            notification_telegram_max_message_chars=99999
        ).notification_telegram_max_message_chars_safe
        == 4096
    )
    assert (
        Settings(
            notification_telegram_max_message_chars=100
        ).notification_telegram_max_message_chars_safe
        == 100
    )


def test_token_ttl_seconds() -> None:
    assert (
        Settings(
            notification_telegram_binding_token_ttl_days=30
        ).notification_telegram_binding_token_ttl_seconds
        == 30 * 86400
    )
    # 0 трактуется как «не задан» → дефолт 30 дней (floor 1 час не срабатывает для целых дней).
    assert (
        Settings(
            notification_telegram_binding_token_ttl_days=0
        ).notification_telegram_binding_token_ttl_seconds
        == 30 * 86400
    )
    assert (
        Settings(
            notification_telegram_binding_token_ttl_days=1
        ).notification_telegram_binding_token_ttl_seconds
        == 86400
    )


def test_live_send_requires_all_flags() -> None:
    # Даже при включённом live send, без external+telegram live эффективный флаг остаётся False.
    s = Settings(
        notification_telegram_live_send_enabled=True,
        notification_telegram_bot_token="123456:ABC",
    )
    assert s.notification_telegram_live_send_enabled_effective is False
    # Все флаги включены → эффективный True (демонстрация live-ready; в MVP не используется).
    s2 = Settings(
        notification_external_delivery_enabled=True,
        notification_telegram_enabled=True,
        notification_telegram_live_enabled=True,
        notification_telegram_live_send_enabled=True,
        notification_telegram_bot_token="123456:ABCDEF",
    )
    assert s2.notification_telegram_live_send_enabled_effective is True
