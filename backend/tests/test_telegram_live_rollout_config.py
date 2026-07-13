"""Тесты конфигурации Telegram live rollout (v0.6.0). Дефолты безопасны; live не подразумевается."""

from app.config import Settings


def test_defaults_safe() -> None:
    s = Settings()
    assert s.telegram_live_rollout_enabled is True
    assert s.telegram_live_rollout_dry_run is True
    assert s.telegram_live_rollout_run_once_enabled is True
    assert s.telegram_live_rollout_require_confirmation is True


def test_allow_real_send_false() -> None:
    s = Settings()
    assert s.telegram_live_rollout_allow_real_send is False
    assert s.telegram_live_rollout_allow_real_send_effective is False


def test_dry_run_true() -> None:
    s = Settings()
    assert s.telegram_live_rollout_dry_run_effective is True


def test_confirmation_required() -> None:
    s = Settings()
    assert s.telegram_live_rollout_require_confirmation_effective is True
    assert s.telegram_live_rollout_confirmation_text_safe == "ENABLE_TELEGRAM_LIVE"


def test_effective_flags() -> None:
    s = Settings()
    assert s.telegram_live_rollout_enabled_effective is True
    assert s.telegram_live_rollout_run_once_enabled_effective is True
    assert s.telegram_live_rollout_max_attempts_per_post_safe == 1


def test_no_global_live_implied() -> None:
    s = Settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
