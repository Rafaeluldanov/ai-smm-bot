"""Тесты конфигурации уведомлений (v0.5.0): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.notifications_enabled is True
    assert s.notifications_in_app_enabled is True
    assert s.notifications_dry_run is True


def test_external_delivery_disabled() -> None:
    s = _s()
    assert s.notifications_email_enabled is False
    assert s.notifications_digest_enabled is False
    assert s.notifications_webhook_enabled is False
    assert s.notifications_external_delivery_enabled is False
    assert s.notifications_external_delivery_enabled_effective is False


def test_external_delivery_requires_both_flags() -> None:
    # Даже если включить email, без общего флага доставки — эффективно выключено.
    s = _s(notifications_email_enabled=True)
    assert s.notifications_external_delivery_enabled_effective is False
    # И общий флаг без каналов — тоже выключено.
    s2 = _s(notifications_external_delivery_enabled=True)
    assert s2.notifications_external_delivery_enabled_effective is False
    # Только оба вместе → включено.
    s3 = _s(notifications_external_delivery_enabled=True, notifications_email_enabled=True)
    assert s3.notifications_external_delivery_enabled_effective is True


def test_worker_disabled() -> None:
    assert _s().notifications_worker_enabled is False


def test_in_app_effective() -> None:
    assert _s().notifications_in_app_enabled_effective is True
    assert _s(notifications_enabled=False).notifications_in_app_enabled_effective is False


def test_windows_and_sla_seconds() -> None:
    assert _s(notifications_dedup_window_minutes=30).notifications_dedup_window_seconds == 1800
    assert _s(notifications_overdue_grace_hours=24).notifications_overdue_grace_seconds == 86400
    assert _s(media_curation_review_sla_hours=72).media_curation_review_sla_seconds == 72 * 3600
    assert _s(post_review_sla_hours=48).post_review_sla_seconds == 48 * 3600
    assert _s(experiment_review_sla_hours=72).experiment_review_sla_seconds == 72 * 3600
    assert _s(notifications_max_per_user=0).notifications_max_per_user_safe >= 1


def test_parsing_works() -> None:
    s = _s(
        notifications_mention_enabled=False,
        notifications_overdue_scan_enabled=False,
        notifications_max_per_user=250,
    )
    assert s.notifications_mention_enabled is False
    assert s.notifications_overdue_scan_enabled is False
    assert s.notifications_max_per_user == 250


def test_no_live_flag_implied() -> None:
    s = _s(notifications_enabled=True, notifications_in_app_enabled=True)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.notifications_external_delivery_enabled is False
