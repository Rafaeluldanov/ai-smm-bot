"""Тесты фонового scheduler-worker (offline, без live-публикации)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import scheduler_worker_repository as lease_repo
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.scheduler_worker_service import LEASE_KEY, SchedulerWorkerService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)  # понедельник 13:00 (после 12:00)


def _seed(db: Session, slug: str = "teeon", connect: bool = True, balance: int = 500) -> int:
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    config = crm.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug)
    )
    category = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id, config_id=config.id, title="C", cta="CTA"
        ),
    )
    crm.create_plan(
        db,
        CrmPublishingPlanCreate(
            project_id=project.id,
            config_id=config.id,
            category_id=category.id,
            weekdays=[0],
            publish_times=["12:00"],
            platforms=["telegram"],
        ),
    )
    if connect:
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
        )
    if balance:
        BillingService().manual_topup(db, account.id, balance, idempotency_key=f"seed-{slug}")
    return project.id


def test_disabled_worker_no_processing(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post import Post

    result = SchedulerWorkerService().tick(db_session, owner_id="o1", now=_NOW, force=False)
    assert result.enabled is False
    assert result.lease_acquired is False
    assert result.targets_scanned == 0
    assert db_session.query(Post).count() == 0


def test_dry_run_tick_no_writes(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post import Post
    from app.models.schedule_run import ScheduleRun

    result = SchedulerWorkerService().tick(
        db_session, owner_id="o1", now=_NOW, dry_run=True, force=True
    )
    assert result.lease_acquired is True
    assert result.dry_run is True
    assert result.targets_scanned == 1
    assert result.drafts_created == 0
    assert db_session.query(Post).count() == 0
    assert db_session.query(ScheduleRun).count() == 0


def test_forced_dry_run_discovers_targets(db_session: Session) -> None:
    _seed(db_session)
    targets = SchedulerWorkerService().discover_due_targets(db_session)
    assert len(targets) == 1
    assert targets[0].platform_key == "telegram"


def test_create_drafts_tick(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post import Post
    from app.models.schedule_run import ScheduleRun

    result = SchedulerWorkerService().tick(
        db_session, owner_id="o1", now=_NOW, dry_run=False, force=True
    )
    assert result.drafts_created == 1
    assert result.schedule_runs_created == 1
    assert db_session.query(Post).count() == 1
    assert db_session.query(ScheduleRun).count() == 1


def test_idempotent_ticks_no_duplicate(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post import Post

    svc = SchedulerWorkerService()
    svc.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    second = svc.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert second.drafts_created == 0
    assert second.skipped == 1
    assert db_session.query(Post).count() == 1


def test_lease_prevents_concurrent_worker(db_session: Session) -> None:
    _seed(db_session)
    # Другой worker держит активную lease.
    lease_repo.acquire_lease(db_session, LEASE_KEY, "other:1:aa", 300, now=_NOW)
    result = SchedulerWorkerService().tick(
        db_session, owner_id="o1", now=_NOW, dry_run=True, force=True
    )
    assert result.lease_acquired is False
    assert result.targets_scanned == 0


def test_no_live_publish_and_no_secrets(db_session: Session) -> None:
    _seed(db_session)
    from app.models.post_publication import PostPublication

    svc = SchedulerWorkerService()
    result = svc.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"
    assert _TOKEN not in str(result.as_dict())


def test_worker_source_has_no_live_publish() -> None:
    """Статическая проверка: worker не импортирует/вызывает publish_due и live-публикацию."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    files = [
        root / "services" / "scheduler_worker_service.py",
        root / "scripts" / "scheduler_worker_tick.py",
        root / "scripts" / "scheduler_worker_loop.py",
        root / "api" / "scheduler_worker.py",
    ]
    for path in files:
        src = path.read_text(encoding="utf-8")
        assert "import publish_due" not in src
        assert "publish_due(" not in src
        assert ".publish_due" not in src
        assert "publish_post(" not in src
        assert "media_publish" not in src


def test_missing_connection_counts(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    _seed(db_session, slug="nocon", connect=False)
    from app.config import Settings
    from app.models.post import Post
    from app.services import platform_connection_service as pcs

    clean = Settings(_env_file=None, app_env="local")
    monkeypatch.setattr(pcs, "get_settings", lambda: clean)
    result = SchedulerWorkerService().tick(
        db_session, owner_id="o1", now=_NOW, dry_run=False, force=True
    )
    assert result.missing_credentials == 1
    assert db_session.query(Post).count() == 0
