"""Тесты конфигурации курирования медиатеки (v0.4.8): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.media_curation_enabled is True
    assert s.media_curation_worker_enabled is False
    assert s.media_curation_dry_run is True


def test_worker_disabled_by_default() -> None:
    assert _s().media_curation_worker_enabled_effective is False


def test_dry_run_true_by_default() -> None:
    assert _s().media_curation_dry_run_effective is True


def test_auto_apply_false_by_default() -> None:
    assert _s().media_curation_auto_apply_tags is False


def test_auto_hide_false_by_default() -> None:
    assert _s().media_curation_auto_hide_duplicates is False


def test_auto_delete_false_by_default() -> None:
    assert _s().media_curation_auto_delete_enabled is False


def test_external_ai_false_by_default() -> None:
    assert _s().media_curation_external_ai_enabled is False


def test_worker_effective_requires_both_flags() -> None:
    s = _s(media_curation_worker_enabled=True, media_curation_enabled=False)
    assert s.media_curation_worker_enabled_effective is False
    s2 = _s(media_curation_worker_enabled=True)
    assert s2.media_curation_worker_enabled_effective is True


def test_min_confidence_clamped() -> None:
    assert _s(media_curation_min_confidence=0.55).media_curation_min_confidence_safe == 0.55
    assert _s(media_curation_min_confidence=5).media_curation_min_confidence_safe == 1.0
    assert _s(media_curation_min_confidence=-1).media_curation_min_confidence_safe == 0.0


def test_max_tasks_and_expire_safe() -> None:
    assert _s(media_curation_max_tasks_per_run=100).media_curation_max_tasks_per_run_safe == 100
    assert _s(media_curation_max_tasks_per_run=0).media_curation_max_tasks_per_run_safe >= 1
    assert _s(media_curation_task_expire_days=30).media_curation_task_expire_seconds == 30 * 86400


def test_toggles_parse() -> None:
    s = _s(
        media_curation_use_fingerprints=False,
        media_curation_use_quality=False,
        media_curation_use_learning=False,
        media_curation_external_ai_enabled=False,
    )
    assert s.media_curation_use_fingerprints is False
    assert s.media_curation_use_quality is False
    assert s.media_curation_use_learning is False
    assert s.media_curation_external_ai_enabled is False


def test_no_live_flag_implied() -> None:
    s = _s(media_curation_worker_enabled=True, media_curation_dry_run=False)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.media_curation_external_ai_enabled is False
    assert s.media_curation_auto_delete_enabled is False
    assert s.media_curation_auto_apply_tags is False
