"""Тесты конфигурации safety-слоя уведомлений (v0.5.2): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.notification_safety_enabled is True
    assert s.notification_safety_enabled_effective is True


def test_unsubscribe_rate_suppression_enabled() -> None:
    s = _s()
    assert s.notification_unsubscribe_enabled_effective is True
    assert s.notification_rate_limit_enabled_effective is True
    assert s.notification_suppression_enabled_effective is True


def test_live_webhook_false() -> None:
    s = _s()
    assert s.notification_webhook_subscriptions_live_enabled is False
    assert s.notification_webhook_subscriptions_live_enabled_effective is False


def test_webhook_subscriptions_enabled_but_live_off() -> None:
    s = _s()
    assert s.notification_webhook_subscriptions_enabled_effective is True
    # Даже если включить live-флаг, без external delivery — эффективно выключено.
    s2 = _s(notification_webhook_subscriptions_live_enabled=True)
    assert s2.notification_webhook_subscriptions_live_enabled_effective is False
    # Только external + subs + live → включено.
    s3 = _s(
        notification_external_delivery_enabled=True,
        notification_webhook_subscriptions_live_enabled=True,
    )
    assert s3.notification_webhook_subscriptions_live_enabled_effective is True


def test_external_delivery_still_false() -> None:
    s = _s()
    assert s.notification_external_delivery_enabled is False
    assert s.notification_external_delivery_enabled_effective is False


def test_ttls_and_thresholds_safe() -> None:
    assert _s(notification_suppression_ttl_hours=24).notification_suppression_ttl_seconds == 86400
    assert (
        _s(notification_unsubscribe_token_ttl_days=365).notification_unsubscribe_token_ttl_seconds
        == 365 * 86400
    )
    assert (
        _s(
            notification_suppression_failure_threshold=5
        ).notification_suppression_failure_threshold_safe
        == 5
    )
    assert (
        _s(
            notification_suppression_failure_threshold=0
        ).notification_suppression_failure_threshold_safe
        >= 1
    )


def test_unsubscribe_secret_falls_back() -> None:
    # Вне production секрет токена отписки берётся из auth-фолбэка, если не задан.
    assert bool(_s().notification_unsubscribe_token_secret_effective)


def test_safety_disabled_cascades() -> None:
    s = _s(notification_safety_enabled=False)
    assert s.notification_safety_enabled_effective is False
    assert s.notification_unsubscribe_enabled_effective is False
    assert s.notification_rate_limit_enabled_effective is False
    assert s.notification_suppression_enabled_effective is False


def test_no_live_flag_implied() -> None:
    s = _s()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.notification_webhook_subscriptions_live_enabled is False
