"""Тесты конфигурации оценки качества медиа (v0.4.6): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.media_quality_scoring_enabled is True
    assert s.media_quality_scoring_worker_enabled is False
    assert s.media_quality_scoring_dry_run is True


def test_worker_disabled_by_default() -> None:
    assert _s().media_quality_scoring_worker_enabled_effective is False


def test_dry_run_true_by_default() -> None:
    assert _s().media_quality_scoring_dry_run_effective is True


def test_external_ai_false_by_default() -> None:
    assert _s().media_quality_external_ai_enabled is False


def test_auto_retags_false_by_default() -> None:
    assert _s().media_quality_auto_retags_enabled is False


def test_worker_effective_requires_both_flags() -> None:
    s = _s(media_quality_scoring_worker_enabled=True, media_quality_scoring_enabled=False)
    assert s.media_quality_scoring_worker_enabled_effective is False
    s2 = _s(media_quality_scoring_worker_enabled=True)
    assert s2.media_quality_scoring_worker_enabled_effective is True


def test_good_excellent_scores_clamped() -> None:
    assert _s(media_quality_min_good_score=70).media_quality_min_good_score_safe == 70
    assert _s(media_quality_min_good_score=200).media_quality_min_good_score_safe == 100
    assert _s(media_quality_min_good_score=-5).media_quality_min_good_score_safe == 0
    # excellent не ниже good.
    assert (
        _s(
            media_quality_min_good_score=80, media_quality_min_excellent_score=50
        ).media_quality_min_excellent_score_safe
        == 80
    )


def test_recency_and_fatigue_safe() -> None:
    s = _s(media_quality_recency_days=60, media_quality_fatigue_window_days=14)
    assert s.media_quality_recency_days_safe == 60
    assert s.media_quality_fatigue_window_days_safe == 14
    assert _s(media_quality_recency_days=0).media_quality_recency_days_safe >= 1


def test_toggles_parse() -> None:
    s = _s(
        media_quality_dedup_enabled=False,
        media_quality_platform_weighting_enabled=False,
        media_quality_auto_retags_enabled=False,
        media_quality_external_ai_enabled=False,
    )
    assert s.media_quality_dedup_enabled is False
    assert s.media_quality_platform_weighting_enabled is False
    assert s.media_quality_auto_retags_enabled is False
    assert s.media_quality_external_ai_enabled is False


def test_no_live_flag_implied() -> None:
    s = _s(media_quality_scoring_worker_enabled=True, media_quality_scoring_dry_run=False)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    # Даже при включённом worker внешний AI и авто-ретегирование остаются выключены.
    assert s.media_quality_external_ai_enabled is False
    assert s.media_quality_auto_retags_enabled is False
