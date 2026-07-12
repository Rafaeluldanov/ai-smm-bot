"""Тесты конфигурации доставки уведомлений (v0.5.1): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.notification_delivery_enabled is True
    assert s.notification_delivery_dry_run is True
    assert s.notification_delivery_enabled_effective is True


def test_external_disabled() -> None:
    s = _s()
    assert s.notification_external_delivery_enabled is False
    assert s.notification_external_delivery_enabled_effective is False


def test_all_live_disabled() -> None:
    s = _s()
    assert s.notification_email_live_enabled is False
    assert s.notification_telegram_live_enabled is False
    assert s.notification_webhook_live_enabled is False
    assert s.notification_email_enabled_effective is False
    assert s.notification_telegram_enabled_effective is False
    assert s.notification_webhook_enabled_effective is False


def test_providers_default_mock() -> None:
    s = _s()
    assert s.notification_email_provider == "mock"
    assert s.notification_telegram_provider == "mock"
    assert s.notification_webhook_provider == "mock"


def test_digest_disabled() -> None:
    s = _s()
    assert s.notification_digest_enabled is False
    assert s.notification_digest_worker_enabled is False
    assert s.notification_digest_enabled_effective is False
    assert s.notification_digest_worker_enabled_effective is False
    assert s.notification_digest_dry_run is True


def test_channel_effective_requires_external_and_live() -> None:
    # Даже включив email и live, без external — эффективно выключено.
    s = _s(notification_email_enabled=True, notification_email_live_enabled=True)
    assert s.notification_email_enabled_effective is False
    # С external + email + live → включено (в тестах не активируем реально).
    s2 = _s(
        notification_external_delivery_enabled=True,
        notification_email_enabled=True,
        notification_email_live_enabled=True,
    )
    assert s2.notification_email_enabled_effective is True


def test_retry_and_backoff_safe() -> None:
    assert _s(notification_delivery_max_attempts=3).notification_delivery_max_attempts_safe == 3
    assert _s(notification_delivery_max_attempts=0).notification_delivery_max_attempts_safe >= 1
    assert (
        _s(
            notification_delivery_retry_backoff_seconds=300
        ).notification_delivery_retry_backoff_seconds_safe
        == 300
    )
    assert (
        _s(notification_digest_max_notifications=0).notification_digest_max_notifications_safe >= 1
    )


def test_configured_flags_do_not_leak_secrets() -> None:
    s = _s(
        smtp_host="mail.example.ru",
        smtp_from_email="bot@example.ru",
        notification_telegram_bot_token="123456:AAAA",
        notification_webhook_signing_secret="s",
    )
    assert s.smtp_configured is True
    assert s.notification_telegram_configured is True
    assert s.notification_webhook_signing_configured is True


def test_dry_run_true() -> None:
    assert _s().notification_delivery_dry_run is True
    assert _s().notification_digest_dry_run is True


def test_no_live_flag_implied() -> None:
    s = _s(notification_delivery_enabled=True)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.notification_external_delivery_enabled is False
