"""Тесты конфигурации автовыбора медиа (v0.4.5): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.auto_media_selection_enabled is True
    assert s.auto_media_selection_worker_enabled is False
    assert s.auto_media_selection_dry_run is True


def test_worker_disabled_by_default() -> None:
    assert _s().auto_media_selection_worker_enabled_effective is False


def test_dry_run_true_by_default() -> None:
    assert _s().auto_media_selection_dry_run_effective is True


def test_public_links_auto_create_false_by_default() -> None:
    assert _s().auto_media_selection_create_public_links is False


def test_worker_effective_requires_both_flags() -> None:
    s = _s(auto_media_selection_worker_enabled=True, auto_media_selection_enabled=False)
    assert s.auto_media_selection_worker_enabled_effective is False
    s2 = _s(auto_media_selection_worker_enabled=True)
    assert s2.auto_media_selection_worker_enabled_effective is True


def test_min_confidence_parsed_and_clamped() -> None:
    assert (
        _s(auto_media_selection_min_confidence=0.7).auto_media_selection_min_confidence_safe == 0.7
    )
    assert _s(auto_media_selection_min_confidence=5).auto_media_selection_min_confidence_safe == 1.0
    assert (
        _s(auto_media_selection_min_confidence=-1).auto_media_selection_min_confidence_safe == 0.0
    )


def test_recency_and_fatigue_safe() -> None:
    s = _s(auto_media_selection_recency_days=60, auto_media_selection_fatigue_window_days=14)
    assert s.auto_media_selection_recency_days_safe == 60
    assert s.auto_media_selection_fatigue_window_days_safe == 14
    assert _s(auto_media_selection_recency_days=0).auto_media_selection_recency_days_safe >= 1


def test_max_images_for_platform() -> None:
    s = _s()
    assert s.auto_media_selection_max_images_for_platform("telegram") == 10
    assert s.auto_media_selection_max_images_for_platform("vk") == 5
    assert s.auto_media_selection_max_images_for_platform("instagram") == 10
    # Неизвестная платформа → безопасный минимум 1.
    assert s.auto_media_selection_max_images_for_platform("website") >= 1
    assert s.auto_media_selection_max_images_for_platform(None) >= 1


def test_toggles_parse() -> None:
    s = _s(
        auto_media_selection_use_ab_winners=False,
        auto_media_selection_use_metrics=False,
        auto_media_selection_use_client_feedback=False,
        auto_media_selection_require_media_for_media_plans=True,
        auto_media_selection_create_public_links=False,
    )
    assert s.auto_media_selection_use_ab_winners is False
    assert s.auto_media_selection_use_metrics is False
    assert s.auto_media_selection_use_client_feedback is False
    assert s.auto_media_selection_require_media_for_media_plans is True
    assert s.auto_media_selection_create_public_links is False


def test_no_live_flag_implied() -> None:
    s = _s(auto_media_selection_worker_enabled=True, auto_media_selection_dry_run=False)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.schedule_experiments_enabled is False
    # Даже при включённом worker публичные ссылки автоматически не создаются.
    assert s.auto_media_selection_create_public_links is False
