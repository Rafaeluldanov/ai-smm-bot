"""Тесты сервиса похожести/дедупликации медиа (v0.4.7).

Offline; без внешнего AI/сети/live. Проверяют сравнение fingerprint, кластеры дублей, выбор
canonical и изоляцию проектов (без межпроектного сравнения).
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_duplicate_cluster_repository,
    media_fingerprint_repository,
    media_quality_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_similarity_service import MediaSimilarityService


def _media(
    db: Session, project_id: int, key: str, status: str = "approved", tags: dict | None = None
) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=f"{key}.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status=status,
            tags=tags if tags is not None else {"products": ["мерч"]},
        ),
    )
    db.commit()
    return asset.id


def _fp(db: Session, project_id: int, asset_id: int, sha=None, avg=None, dh=None):  # noqa: ANN202
    return media_fingerprint_repository.create_fingerprint(
        db,
        project_id=project_id,
        media_asset_id=asset_id,
        status="calculated",
        source="media_variant",
        file_sha256=sha,
        perceptual_hash=avg,
        average_hash=avg,
        difference_hash=dh,
        metadata_signature={},
        tag_signature={"signature": ""},
    )


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project


def _svc(**flags: object) -> MediaSimilarityService:
    return MediaSimilarityService(settings=Settings(**flags))


def test_exact_sha256_duplicate_score_one() -> None:
    left = {"file_sha256": "abc", "metadata_signature": {}, "tag_signature": {}}
    right = {"file_sha256": "abc", "metadata_signature": {}, "tag_signature": {}}
    cmp = _svc().compare_fingerprints(left, right)
    assert cmp["similarity_score"] == 1.0
    assert cmp["similarity_type"] == "exact_duplicate"


def test_near_perceptual_hash_duplicate() -> None:
    left = {"average_hash": "0000000000000000", "metadata_signature": {}, "tag_signature": {}}
    right = {"average_hash": "0000000000000001", "metadata_signature": {}, "tag_signature": {}}
    cmp = _svc().compare_fingerprints(left, right)
    assert cmp["similarity_type"] == "near_duplicate"
    assert cmp["similarity_score"] >= 0.9
    assert cmp["hash_distance"] == 1


def test_same_tag_signature_only_lower_score() -> None:
    left = {"tag_signature": {"signature": "a|b|c"}, "metadata_signature": {}}
    right = {"tag_signature": {"signature": "a|b|c"}, "metadata_signature": {}}
    cmp = _svc().compare_fingerprints(left, right)
    assert cmp["similarity_type"] == "same_series"
    assert cmp["similarity_score"] < 0.82


def test_hamming_distance() -> None:
    svc = _svc()
    assert svc.hamming_distance("ff", "00") == 8
    assert svc.hamming_distance("0", "0") == 0
    assert svc.hamming_distance(None, "0") == 64


def test_find_duplicate_clusters_groups_similar(db_session: Session) -> None:
    _acc, project = _seed(db_session, "sim-cluster")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _c = _media(db_session, project.id, "c")
    # A и B — визуальные дубли (одинаковый average_hash); C уникален.
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    _fp(db_session, project.id, b, avg="ffffffffffffffff")
    _fp(db_session, project.id, _c, avg="0000000000000000")
    result = _svc().find_duplicate_clusters(db_session, project.id, dry_run=False)
    assert result["clusters_created"] == 1
    clusters = media_duplicate_cluster_repository.list_for_project(db_session, project.id)
    assert len(clusters) == 1
    assert set(clusters[0].member_media_asset_ids) == {a, b}
    assert clusters[0].similarity_score >= 0.9


def test_find_duplicate_clusters_dry_run_no_write(db_session: Session) -> None:
    _acc, project = _seed(db_session, "sim-dry")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _fp(db_session, project.id, a, sha="same")
    _fp(db_session, project.id, b, sha="same")
    result = _svc().find_duplicate_clusters(db_session, project.id, dry_run=True)
    assert result["clusters_found"] == 1
    assert result["clusters_created"] == 0
    assert media_duplicate_cluster_repository.list_for_project(db_session, project.id) == []


def test_choose_canonical_prefers_approved_and_quality(db_session: Session) -> None:
    _acc, project = _seed(db_session, "sim-canon")
    good = _media(db_session, project.id, "good", status="approved")
    weak = _media(db_session, project.id, "weak", status="approved")
    media_quality_repository.create_snapshot(
        db_session, project_id=project.id, media_asset_id=good, status="excellent", overall_score=95
    )
    media_quality_repository.create_snapshot(
        db_session, project_id=project.id, media_asset_id=weak, status="weak", overall_score=40
    )
    canonical = _svc().choose_canonical_media(db_session, project.id, [good, weak])
    assert canonical == good


def test_no_cross_project_comparison(db_session: Session) -> None:
    _a1, p1 = _seed(db_session, "sim-iso1")
    _a2, p2 = _seed(db_session, "sim-iso2")
    a1 = _media(db_session, p1.id, "a1")
    a2 = _media(db_session, p2.id, "a2")
    _fp(db_session, p1.id, a1, sha="shared")
    _fp(db_session, p2.id, a2, sha="shared")  # тот же хэш, но другой проект
    # Кластеры проекта 1 не должны включать медиа проекта 2.
    result = _svc().find_duplicate_clusters(db_session, p1.id, dry_run=False)
    assert result["clusters_created"] == 0  # в p1 только один fingerprint
    assert media_duplicate_cluster_repository.list_for_project(db_session, p2.id) == []
