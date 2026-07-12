"""Тесты влияния fingerprint/дублей на оценку качества медиа (v0.4.7).

Offline; без внешнего AI/live. Проверяют, что точные/визуальные дубли и серии снижают
uniqueness и добавляют issue-коды; без межпроектного смешивания.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_duplicate_cluster_repository,
    media_fingerprint_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_quality_service import MediaQualityService


def _media(db: Session, project_id: int, key: str) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=f"{key}.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={"products": ["мерч"], "technologies": ["dtf"]},
        ),
    )
    db.commit()
    return asset.id


def _fp(db: Session, project_id: int, asset_id: int, sha=None, avg=None) -> None:
    media_fingerprint_repository.create_fingerprint(
        db,
        project_id=project_id,
        media_asset_id=asset_id,
        status="calculated",
        source="media_variant",
        file_sha256=sha,
        perceptual_hash=avg,
        average_hash=avg,
        metadata_signature={},
        tag_signature={"signature": ""},
    )


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    return account, project


def _svc() -> MediaQualityService:
    return MediaQualityService(settings=Settings())


def test_exact_duplicate_lowers_uniqueness(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fpq-exact")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _fp(db_session, project.id, a, sha="same")
    _fp(db_session, project.id, b, sha="same")
    result = _svc().score_media_asset(db_session, project.id, a, "telegram", dry_run=True)
    assert result["uniqueness_score"] <= 30
    assert "duplicate_candidate" in result["issue_codes"]


def test_near_duplicate_issue(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fpq-near")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    _fp(db_session, project.id, b, avg="ffffffffffffffff")
    result = _svc().score_media_asset(db_session, project.id, a, "telegram", dry_run=True)
    assert result["uniqueness_score"] <= 45
    assert "duplicate_candidate" in result["issue_codes"]


def test_same_series_weaker_penalty(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fpq-series")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    media_duplicate_cluster_repository.create_cluster(
        db_session,
        project_id=project.id,
        status="active",
        cluster_type="same_series",
        canonical_media_asset_id=a,
        member_media_asset_ids=[a, b],
        member_fingerprint_ids=[],
        similarity_score=0.6,
    )
    result = _svc().score_media_asset(db_session, project.id, a, "telegram", dry_run=True)
    assert result["uniqueness_score"] == 70  # серия — лёгкий штраф
    assert "same_series" in result["issue_codes"]


def test_no_cross_project_duplicate(db_session: Session) -> None:
    _a1, p1 = _seed(db_session, "fpq-iso1")
    _a2, p2 = _seed(db_session, "fpq-iso2")
    a1 = _media(db_session, p1.id, "a1")
    a2 = _media(db_session, p2.id, "a2")
    _fp(db_session, p1.id, a1, sha="shared")
    _fp(db_session, p2.id, a2, sha="shared")  # тот же хэш, другой проект
    result = _svc().score_media_asset(db_session, p1.id, a1, "telegram", dry_run=True)
    # Дубль из другого проекта не должен снижать уникальность/давать issue.
    assert result["uniqueness_score"] >= 80
    assert "duplicate_candidate" not in result["issue_codes"]
