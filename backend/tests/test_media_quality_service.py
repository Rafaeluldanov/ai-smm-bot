"""Тесты сервиса оценки качества медиа (v0.4.6).

Offline, без внешнего AI/сети/live-публикаций. Проверяют скоринг, проблемы, дубли,
свежесть, платформенную пригодность, диапазоны, изоляцию и отсутствие путей в ответе.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_quality_repository,
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


def _media(
    db: Session,
    project_id: int,
    key: str,
    tags: dict | None = None,
    status: str = "approved",
    file_name: str = "img.jpg",
    title: str | None = None,
) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status=status,
            title=title,
            tags=tags if tags is not None else {"products": ["мерч"], "technologies": ["dtf"]},
        ),
    )
    db.commit()
    return asset.id


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


def _svc(**flags: object) -> MediaQualityService:
    return MediaQualityService(settings=Settings(**flags))


def test_score_dry_run_no_writes(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-dry")
    aid = _media(db_session, project.id, "a")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert result["writes"] is False
    assert 0 <= result["overall_score"] <= 100
    assert media_quality_repository.list_for_project(db_session, project.id) == []


def test_score_write_creates_snapshot(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-write")
    aid = _media(db_session, project.id, "a")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=False)
    assert result["writes"] is True
    rows = media_quality_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].media_asset_id == aid
    assert rows[0].overall_score is not None


def test_missing_tags_issue(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-notags")
    aid = _media(db_session, project.id, "a", tags={})
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert "missing_tags" in result["issue_codes"]
    assert "missing_product_tags" in result["issue_codes"]
    assert result["status"] == "needs_tags"


def test_heic_conversion_issue(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-heic")
    aid = _media(db_session, project.id, "a", file_name="photo.heic")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert "heic_conversion_needed" in result["issue_codes"]


def test_video_not_supported_issue(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-video")
    aid = _media(db_session, project.id, "a", file_name="clip.mp4", status="approved_video")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert "video_not_supported" in result["issue_codes"]


def test_duplicate_candidate_issue(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-dup")
    _media(db_session, project.id, "a", file_name="same.jpg", title="Одинаковое")
    aid2 = _media(db_session, project.id, "b", file_name="same.jpg", title="Одинаковое")
    result = _svc().score_media_asset(db_session, project.id, aid2, "telegram", dry_run=True)
    assert "duplicate_candidate" in result["issue_codes"]
    assert result["duplicate_of_media_asset_id"] is not None


def test_recently_used_penalty(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-recent")
    aid = _media(db_session, project.id, "a")
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    asset.last_used_at = datetime.now(UTC)
    db_session.commit()
    svc = _svc()
    result = svc.score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert "recently_used" in result["issue_codes"]
    assert result["freshness_score"] < 92  # свежесть штрафуется


def test_instagram_requires_public_url(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-ig")
    aid = _media(db_session, project.id, "a")
    result = _svc().score_media_asset(db_session, project.id, aid, "instagram", dry_run=True)
    assert "instagram_public_url_required" in result["issue_codes"]


def test_overall_score_in_range(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-range")
    aid = _media(db_session, project.id, "a")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    for key in (
        "quality_score",
        "relevance_score",
        "freshness_score",
        "uniqueness_score",
        "platform_fit_score",
        "overall_score",
    ):
        assert 0 <= result[key] <= 100


def test_strong_media_scores_high(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-strong")
    aid = _media(
        db_session,
        project.id,
        "a",
        tags={"products": ["мерч"], "technologies": ["dtf"], "categories": ["мерч"]},
        title="Отличное фото мерча",
    )
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=True)
    assert result["overall_score"] >= 70
    assert result["status"] in ("good", "excellent")


def test_score_project_media_summary(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-batch")
    for i in range(3):
        _media(db_session, project.id, f"a{i}")
    summary = _svc().score_project_media(db_session, project.id, "telegram", dry_run=True)
    assert summary["scanned"] == 3
    assert summary["scored"] == 3
    assert summary["snapshots_created"] == 0  # dry-run
    assert media_quality_repository.list_for_project(db_session, project.id) == []


def test_no_cross_project_mixing(db_session: Session) -> None:
    _a1, p1 = _seed(db_session, "mq-iso1")
    _a2, p2 = _seed(db_session, "mq-iso2")
    aid = _media(db_session, p1.id, "a")
    _svc().score_media_asset(db_session, p1.id, aid, "telegram", dry_run=False)
    assert media_quality_repository.list_for_project(db_session, p2.id) == []
    assert len(media_quality_repository.list_for_project(db_session, p1.id)) == 1


def test_no_internal_path_in_result(db_session: Session) -> None:
    _acc, project = _seed(db_session, "mq-nopath")
    aid = _media(db_session, project.id, "secretfile", file_name="secret-photo.jpg")
    result = _svc().score_media_asset(db_session, project.id, aid, "telegram", dry_run=False)
    blob = str(result)
    assert "disk:/" not in blob
    assert "secret-photo.jpg" not in blob
    assert "secretfile" not in blob


def test_score_media_asset_other_project_rejected(db_session: Session) -> None:
    import pytest

    from app.services.media_quality_service import MediaQualityError

    _a1, p1 = _seed(db_session, "mq-rej1")
    _a2, p2 = _seed(db_session, "mq-rej2")
    aid = _media(db_session, p1.id, "a")
    with pytest.raises(MediaQualityError):
        _svc().score_media_asset(db_session, p2.id, aid, "telegram", dry_run=True)
