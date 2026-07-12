"""Тесты интеграции оценки качества медиа в фоновый worker (v0.4.6).

Offline; никаких live-публикаций и внешнего AI. Проверяют безопасные дефолты (выключено),
dry-run (preview без записи), enabled (снимки), отсутствие live-публикации и publish_due.
"""

import inspect
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post import Post
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
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services import scheduler_worker_service as worker_module
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.scheduler_worker_service import SchedulerWorkerService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)


def _seed(db: Session, slug: str = "wmq") -> int:
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
    for i in range(3):
        media_repo.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project.id,
                file_name="img.jpg",
                yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                source_type="internal",
                license_type=None,
                status="approved",
                tags={"products": ["мерч"], "technologies": ["dtf"]},
            ),
        )
    db.commit()
    return project.id


def _worker(**flags: object) -> SchedulerWorkerService:
    return SchedulerWorkerService(settings=Settings(**flags))


def test_disabled_by_default(db_session: Session) -> None:
    pid = _seed(db_session)
    result = _worker().tick(db_session, owner_id="o1", now=_NOW, dry_run=True, force=True)
    assert result.media_quality_scoring_enabled is False
    assert result.media_quality_snapshots_created == 0
    assert media_quality_repository.list_for_project(db_session, pid) == []


def test_enabled_dry_run_previews_no_writes(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(media_quality_scoring_worker_enabled=True)
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=True, force=True)
    assert result.media_quality_scoring_enabled is True
    assert result.media_quality_scoring_dry_run is True
    assert result.media_quality_assets_scanned > 0
    assert result.media_quality_snapshots_created == 0
    assert media_quality_repository.list_for_project(db_session, pid) == []


def test_enabled_creates_snapshots(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(media_quality_scoring_worker_enabled=True, media_quality_scoring_dry_run=False)
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert result.media_quality_scoring_enabled is True
    assert result.media_quality_snapshots_created >= 3
    assert len(media_quality_repository.list_for_project(db_session, pid)) >= 3


def test_no_live_publish(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post_publication import PostPublication

    worker = _worker(media_quality_scoring_worker_enabled=True, media_quality_scoring_dry_run=False)
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert db_session.query(Post).filter(Post.status == "published").count() == 0
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"
    assert _TOKEN not in str(result.as_dict())


def test_worker_no_publish_due() -> None:
    from app.services import media_quality_service as quality_module

    for mod in (worker_module, quality_module):
        source = inspect.getsource(mod)
        assert "scripts.publish_due" not in source
        assert "import publish_due" not in source
