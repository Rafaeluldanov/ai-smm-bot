"""Тесты влияния fingerprint/дублей на auto media selection (v0.4.7).

Offline; без live. Проверяют, что решение о медиа избегает почти-дублей в media_group,
берёт canonical при только-дублях, пишет diversity_score в generation_notes и не светит пути.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post import Post
from app.repositories import (
    account_repository,
    media_fingerprint_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.schedule_automation_service import ScheduleAutomationService
from app.services.schedule_media_decision_service import ScheduleMediaDecisionService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)


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
            tags={"products": ["мерч"]},
        ),
    )
    db.commit()
    return asset.id


def _fp(db: Session, project_id: int, asset_id: int, avg: str) -> None:
    media_fingerprint_repository.create_fingerprint(
        db,
        project_id=project_id,
        media_asset_id=asset_id,
        status="calculated",
        source="media_variant",
        average_hash=avg,
        perceptual_hash=avg,
        metadata_signature={},
        tag_signature={"signature": ""},
    )


def _seed(db: Session, slug: str, with_plan: bool = False):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    cat = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    if with_plan:
        crm.create_plan(
            db,
            CrmPublishingPlanCreate(
                project_id=project.id,
                config_id=cfg.id,
                category_id=cat.id,
                weekdays=[0],
                publish_times=["12:00"],
                platforms=["telegram"],
            ),
        )
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
        )
        BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    return account, project, cat


def test_media_group_excludes_near_duplicates(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "fpd-group")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    c = _media(db_session, project.id, "c")
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    _fp(db_session, project.id, b, avg="ffffffffffffffff")  # почти-дубль A
    _fp(db_session, project.id, c, avg="0000000000000000")  # уникален
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["media_diversity_summary"]["similar_media_skipped_count"] >= 1
    # Оба почти-дубля A и B не попадают вместе в подборку.
    chosen = set(result["selected_media_asset_ids"])
    assert not ({a, b} <= chosen)


def test_only_duplicates_picks_canonical(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "fpd-only")
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    _fp(db_session, project.id, b, avg="ffffffffffffffff")  # оба — дубли друг друга
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_media_count"] == 1  # только один из дублей
    assert result["media_diversity_summary"]["similar_media_skipped_count"] >= 1


def test_diversity_score_in_generation_notes(db_session: Session) -> None:
    acc, project, _cat = _seed(db_session, "fpd-notes", with_plan=True)
    a = _media(db_session, project.id, "a")
    b = _media(db_session, project.id, "b")
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    _fp(db_session, project.id, b, avg="ffffffffffffffff")
    svc = ScheduleAutomationService(
        settings=Settings(
            auto_media_selection_worker_enabled=True, auto_media_selection_dry_run=False
        )
    )
    svc.run_due(db_session, acc.id, project.id, now=_NOW)
    draft = (
        db_session.query(Post)
        .filter(Post.project_id == project.id, Post.status == "needs_review")
        .order_by(Post.id.desc())
        .first()
    )
    notes = draft.generation_notes or {}
    assert "media_diversity_summary" in notes
    assert "diversity_score" in notes["media_diversity_summary"]


def test_no_paths_or_hash_leaks(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "fpd-nopath")
    a = _media(db_session, project.id, "hiddenfile")
    _fp(db_session, project.id, a, avg="ffffffffffffffff")
    svc = ScheduleMediaDecisionService(settings=Settings())
    result = svc.choose_media_for_schedule(db_session, project.id, "telegram", category=cat)
    blob = str(result["media_diversity_summary"])
    assert "disk:/" not in blob
    assert "hiddenfile" not in blob
