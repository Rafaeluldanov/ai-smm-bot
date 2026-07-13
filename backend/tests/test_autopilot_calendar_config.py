"""Тесты конфигурации Calendar Assistant (v0.5.8). Дефолты безопасны; live-старт выключен."""

from app.config import Settings


def test_defaults_enabled_but_safe() -> None:
    s = Settings()
    assert s.autopilot_calendar_assistant_enabled is True
    assert s.autopilot_calendar_assistant_dry_run is True
    assert s.autopilot_calendar_auto_apply_enabled is True
    assert s.autopilot_calendar_live_start_enabled is False


def test_effective_flags() -> None:
    s = Settings()
    assert s.autopilot_calendar_assistant_enabled_effective is True
    assert s.autopilot_calendar_assistant_dry_run_effective is True
    assert s.autopilot_calendar_auto_apply_enabled_effective is True


def test_safe_defaults() -> None:
    s = Settings()
    assert s.autopilot_calendar_default_preset_safe in {
        "daily",
        "weekdays",
        "three_per_week",
        "two_per_week",
        "custom",
        "launch_campaign",
        "soft_presence",
        "intensive_month",
    }
    assert s.autopilot_calendar_default_goal_safe in {
        "sales",
        "leads",
        "reach",
        "trust",
        "expertise",
        "mixed",
    }
    assert 1 <= s.autopilot_calendar_max_posts_per_day_safe <= 10
    assert 1 <= s.autopilot_calendar_max_platforms_safe <= 10
    assert s.autopilot_calendar_default_timezone_safe


def test_no_live_flags_implied() -> None:
    s = Settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
