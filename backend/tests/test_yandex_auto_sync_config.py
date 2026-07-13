"""Тесты конфигурации авто-синхронизации Яндекс Диска (v0.5.7). Дефолты безопасны."""

from app.config import Settings


def test_defaults_safe() -> None:
    s = Settings()
    assert s.yandex_auto_sync_enabled is True
    assert s.yandex_auto_sync_worker_enabled is False
    assert s.yandex_auto_sync_dry_run is True
    assert s.yandex_auto_sync_network_enabled is False


def test_auto_delete_hide_off() -> None:
    s = Settings()
    assert s.yandex_auto_sync_auto_delete is False
    assert s.yandex_auto_sync_auto_hide is False


def test_effective_flags() -> None:
    s = Settings()
    assert s.yandex_auto_sync_enabled_effective is True
    assert s.yandex_auto_sync_worker_enabled_effective is False
    assert s.yandex_auto_sync_dry_run_effective is True
    assert s.yandex_auto_sync_network_enabled_effective is False


def test_no_live_flags_implied() -> None:
    s = Settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_numeric_clamps() -> None:
    assert (
        Settings(
            yandex_auto_sync_default_frequency_minutes=1
        ).yandex_auto_sync_default_frequency_minutes_safe
        == 5
    )
    assert (
        Settings(
            yandex_auto_sync_default_frequency_minutes=99999
        ).yandex_auto_sync_default_frequency_minutes_safe
        == 1440
    )
    assert (
        Settings(
            yandex_auto_sync_max_projects_per_tick=0
        ).yandex_auto_sync_max_projects_per_tick_safe
        == 20
    )
    assert (
        Settings(yandex_auto_sync_max_files_per_run=0).yandex_auto_sync_max_files_per_run_safe
        == 500
    )
    # рекомендуемый объём не меньше минимума
    s = Settings(yandex_auto_sync_min_media_assets=40, yandex_auto_sync_recommended_media_assets=10)
    assert (
        s.yandex_auto_sync_recommended_media_assets_safe >= s.yandex_auto_sync_min_media_assets_safe
    )
