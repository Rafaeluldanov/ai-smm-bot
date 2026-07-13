"""Тесты конфигурации live-readiness (v0.5.9). Дефолты безопасны; live не подразумевается."""

from app.config import Settings


def test_defaults_safe() -> None:
    s = Settings()
    assert s.live_readiness_enabled is True
    assert s.live_readiness_dry_run is True
    assert s.live_readiness_worker_enabled is False
    assert s.live_readiness_require_confirmation is True


def test_auto_enable_false() -> None:
    s = Settings()
    assert s.live_readiness_auto_enable is False


def test_probe_external_false() -> None:
    s = Settings()
    assert s.live_readiness_probe_external_api is False
    assert s.live_readiness_probe_external_api_effective is False


def test_global_override_false() -> None:
    s = Settings()
    assert s.live_readiness_allow_global_flag_override is False


def test_confirmation_required() -> None:
    s = Settings()
    assert s.live_readiness_require_confirmation_effective is True
    assert s.live_autopilot_confirmation_text_safe == "ENABLE_LIVE_AUTOPILOT"
    assert s.live_platform_confirmation_text_safe == "ENABLE_PLATFORM_LIVE"


def test_effective_flags() -> None:
    s = Settings()
    assert s.live_readiness_enabled_effective is True
    assert s.live_readiness_dry_run_effective is True
    assert s.live_readiness_worker_enabled_effective is False
    assert s.live_readiness_min_score_to_enable_safe == 85


def test_no_live_flag_implied() -> None:
    s = Settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
