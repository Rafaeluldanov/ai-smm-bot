"""Тесты конфигурации автопилота (v0.5.6). Дефолты безопасны; full_auto primary; live off."""

from app.config import Settings


def test_defaults_safe() -> None:
    s = Settings()
    assert s.autopilot_ui_enabled is True
    assert s.autopilot_auto_start_live is False
    assert s.autopilot_health_check_worker_enabled is False
    assert s.autopilot_show_advanced_settings is False
    assert s.autopilot_health_check_dry_run is True


def test_full_auto_primary() -> None:
    s = Settings()
    assert s.autopilot_default_mode_safe == "full_auto"
    assert s.autopilot_full_auto_primary_effective is True


def test_effective_flags() -> None:
    s = Settings()
    assert s.autopilot_ui_enabled_effective is True
    assert s.autopilot_auto_start_live_effective is False
    assert s.autopilot_health_check_worker_enabled_effective is False
    assert s.autopilot_health_check_dry_run_effective is True


def test_mode_clamp() -> None:
    assert Settings(autopilot_default_mode="turbo").autopilot_default_mode_safe == "full_auto"
    assert Settings(autopilot_default_mode="semi_auto").autopilot_default_mode_safe == "semi_auto"


def test_numeric_clamps() -> None:
    # 0 трактуется как «не задано» → дефолт (falsy fallback); отрицательное → нижняя граница.
    assert Settings(autopilot_min_media_assets=0).autopilot_min_media_assets_safe == 5
    assert Settings(autopilot_min_media_assets=-3).autopilot_min_media_assets_safe == 1
    assert Settings(autopilot_default_posts_per_day=-1).autopilot_default_posts_per_day_safe == 1
    assert Settings(autopilot_default_posts_per_day=99).autopilot_default_posts_per_day_safe == 10
    # Рекомендуемый объём не меньше минимума.
    s = Settings(autopilot_min_media_assets=40, autopilot_recommended_media_assets=10)
    assert s.autopilot_recommended_media_assets_safe >= s.autopilot_min_media_assets_safe


def test_publish_time_clamp() -> None:
    assert (
        Settings(autopilot_default_publish_time="99:99").autopilot_default_publish_time_safe
        == "10:00"
    )
    assert (
        Settings(autopilot_default_publish_time="9:5").autopilot_default_publish_time_safe
        == "09:05"
    )


def test_timezone_default() -> None:
    assert (
        Settings(autopilot_default_timezone="").autopilot_default_timezone_safe == "Europe/Moscow"
    )
