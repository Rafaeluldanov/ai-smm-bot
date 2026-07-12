"""Тесты конфигурации предложений экспериментов (v0.4.3): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.experiment_suggestions_enabled is True
    assert s.experiment_suggestions_worker_enabled is False
    assert s.experiment_suggestions_auto_create is False
    assert s.experiment_suggestions_dry_run is True
    assert s.schedule_experiments_enabled is False


def test_worker_disabled_by_default() -> None:
    assert _s().experiment_suggestions_worker_enabled_effective is False


def test_auto_create_disabled_by_default() -> None:
    assert _s().experiment_suggestions_auto_create_effective is False


def test_worker_effective_requires_both_flags() -> None:
    # worker_enabled=true, но suggestions_enabled=false → worker недоступен.
    s = _s(experiment_suggestions_worker_enabled=True, experiment_suggestions_enabled=False)
    assert s.experiment_suggestions_worker_enabled_effective is False
    s2 = _s(experiment_suggestions_worker_enabled=True)
    assert s2.experiment_suggestions_worker_enabled_effective is True


def test_auto_create_requires_worker_enabled() -> None:
    # auto_create=true, но worker выключен → auto_create недоступен.
    s = _s(experiment_suggestions_auto_create=True)
    assert s.experiment_suggestions_auto_create_effective is False
    s2 = _s(experiment_suggestions_worker_enabled=True, experiment_suggestions_auto_create=True)
    assert s2.experiment_suggestions_auto_create_effective is True


def test_min_confidence_parsed() -> None:
    s = _s(experiment_suggestions_min_confidence=0.7)
    assert s.experiment_suggestions_min_confidence == 0.7


def test_cooldown_and_expire_seconds() -> None:
    s = _s(experiment_suggestions_cooldown_hours=24, experiment_suggestions_expire_days=14)
    assert s.experiment_suggestions_cooldown_seconds == 24 * 3600
    assert s.experiment_suggestions_expire_seconds == 14 * 86400


def test_no_live_flag_implied() -> None:
    # Включение предложений не включает никакие live-флаги публикации/платежей.
    s = _s(
        experiment_suggestions_worker_enabled=True,
        experiment_suggestions_auto_create=True,
    )
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
