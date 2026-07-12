"""Тесты конфигурации fingerprint/дедупликации медиа (v0.4.7): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.media_fingerprinting_enabled is True
    assert s.media_fingerprinting_worker_enabled is False
    assert s.media_fingerprinting_dry_run is True


def test_worker_disabled_by_default() -> None:
    assert _s().media_fingerprinting_worker_enabled_effective is False


def test_dry_run_true_by_default() -> None:
    assert _s().media_fingerprinting_dry_run_effective is True


def test_yandex_download_false_by_default() -> None:
    assert _s().media_fingerprinting_use_yandex_download is False


def test_external_ai_false_by_default() -> None:
    assert _s().media_fingerprinting_external_ai_enabled is False


def test_auto_delete_false_by_default() -> None:
    assert _s().media_duplicate_auto_delete_enabled is False
    assert _s().media_duplicate_auto_hide_enabled is False


def test_worker_effective_requires_both_flags() -> None:
    s = _s(media_fingerprinting_worker_enabled=True, media_fingerprinting_enabled=False)
    assert s.media_fingerprinting_worker_enabled_effective is False
    s2 = _s(media_fingerprinting_worker_enabled=True)
    assert s2.media_fingerprinting_worker_enabled_effective is True


def test_near_hash_distance_clamped() -> None:
    assert _s(media_similarity_near_hash_distance=6).media_similarity_near_hash_distance_safe == 6
    assert (
        _s(media_similarity_near_hash_distance=100).media_similarity_near_hash_distance_safe == 32
    )
    assert _s(media_similarity_near_hash_distance=0).media_similarity_near_hash_distance_safe == 1


def test_cluster_min_score_clamped() -> None:
    assert _s(media_duplicate_cluster_min_score=0.82).media_duplicate_cluster_min_score_safe == 0.82
    assert _s(media_duplicate_cluster_min_score=5).media_duplicate_cluster_min_score_safe == 1.0
    assert _s(media_duplicate_cluster_min_score=-1).media_duplicate_cluster_min_score_safe == 0.0


def test_max_assets_per_run_safe() -> None:
    assert (
        _s(media_fingerprinting_max_assets_per_run=200).media_fingerprinting_max_assets_per_run_safe
        == 200
    )
    assert (
        _s(media_fingerprinting_max_assets_per_run=0).media_fingerprinting_max_assets_per_run_safe
        >= 1
    )


def test_toggles_parse() -> None:
    s = _s(
        media_fingerprinting_use_variants=False,
        media_similarity_dedup_enabled=False,
        media_duplicate_auto_delete_enabled=False,
    )
    assert s.media_fingerprinting_use_variants is False
    assert s.media_similarity_dedup_enabled is False
    assert s.media_duplicate_auto_delete_enabled is False


def test_no_live_flag_implied() -> None:
    s = _s(media_fingerprinting_worker_enabled=True, media_fingerprinting_dry_run=False)
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.media_fingerprinting_external_ai_enabled is False
    assert s.media_duplicate_auto_delete_enabled is False
    assert s.media_fingerprinting_use_yandex_download is False
