"""Тесты конфигурации автовыбора темы (v0.4.4): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.auto_topic_selection_enabled is True
    assert s.auto_topic_selection_worker_enabled is False
    assert s.auto_topic_selection_dry_run is True


def test_worker_disabled_by_default() -> None:
    assert _s().auto_topic_selection_worker_enabled_effective is False


def test_dry_run_true_by_default() -> None:
    assert _s().auto_topic_selection_dry_run_effective is True


def test_worker_effective_requires_both_flags() -> None:
    s = _s(auto_topic_selection_worker_enabled=True, auto_topic_selection_enabled=False)
    assert s.auto_topic_selection_worker_enabled_effective is False
    s2 = _s(auto_topic_selection_worker_enabled=True)
    assert s2.auto_topic_selection_worker_enabled_effective is True


def test_min_confidence_parsed_and_clamped() -> None:
    assert (
        _s(auto_topic_selection_min_confidence=0.7).auto_topic_selection_min_confidence_safe == 0.7
    )
    assert _s(auto_topic_selection_min_confidence=5).auto_topic_selection_min_confidence_safe == 1.0
    assert (
        _s(auto_topic_selection_min_confidence=-1).auto_topic_selection_min_confidence_safe == 0.0
    )


def test_recency_and_fatigue_safe() -> None:
    s = _s(auto_topic_selection_recency_days=60, auto_topic_selection_fatigue_window_days=14)
    assert s.auto_topic_selection_recency_days_safe == 60
    assert s.auto_topic_selection_fatigue_window_days_safe == 14
    assert _s(auto_topic_selection_recency_days=0).auto_topic_selection_recency_days_safe >= 1


def test_toggles_parse() -> None:
    s = _s(
        auto_topic_selection_use_ab_winners=False,
        auto_topic_selection_use_experiment_suggestions=False,
        auto_topic_selection_use_metrics=False,
        auto_topic_selection_fallback_to_crm_category=False,
    )
    assert s.auto_topic_selection_use_ab_winners is False
    assert s.auto_topic_selection_use_experiment_suggestions is False
    assert s.auto_topic_selection_use_metrics is False
    assert s.auto_topic_selection_fallback_to_crm_category is False


def test_no_live_flag_implied() -> None:
    s = _s(auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.schedule_experiments_enabled is False
