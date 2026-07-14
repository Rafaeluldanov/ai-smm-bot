"""Интеграция мониторинга × schedule automation / worker (v0.6.1, offline).

Ключевой инвариант: стоп-кран реально останавливает публикацию, потому что выключает
per-project live — состояние, которое движок уже учитывает (_filter_by_live_readiness).
Плюс: worker-подшаг мониторинга выключен по умолчанию (no-op) и не публикует.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.publishing import FakePublishingClient
from app.models.live_autopilot_monitor_snapshot import LiveAutopilotMonitorSnapshot
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import live_readiness_repository as lrr
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.live_autopilot_monitoring_service import LiveAutopilotMonitoringService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.schedule_automation_service import ScheduleAutomationService
from app.services.scheduler_worker_service import SchedulerWorkerService

_DATE = "2026-07-13"  # Monday
_NOW = datetime(2026, 7, 13, 12, 30, tzinfo=UTC)


def _seed(db: Session, slug: str):  # noqa: ANN202
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
            project_id=project.id,
            config_id=config.id,
            title="Футболки",
            cta="Заказать со скидкой 20% за 990 руб",
        ),
    )
    plan = crm.create_plan(
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
    plan.automation_mode = "full_auto"
    plan.auto_publish_enabled = True
    plan.min_quality_score_for_auto = 10
    plan.require_review_before_first_auto = False
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@x"}
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, plan


def _fake_publication() -> PostPublicationService:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram", live_enabled=True)}
    )
    return PostPublicationService(registry=registry, default_targets={"telegram": "@x"})


def _enable_readiness(db: Session, account_id: int, project_id: int) -> None:
    pp = lrr.get_or_create_project_profile(db, account_id, project_id)
    lrr.update_project_profile(
        db, pp, {"status": "ready", "project_live_enabled": True, "full_auto_live_enabled": True}
    )
    plat = lrr.get_or_create_platform_profile(db, account_id, project_id, "telegram")
    lrr.update_platform_profile(db, plat, {"status": "ready", "platform_live_enabled": True})
    db.commit()


def test_baseline_publishes_with_all_gates(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "lamint-go")
    _enable_readiness(db_session, acc.id, project.id)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    assert res["entries"][0]["auto_published"] is True


def test_pause_stops_publishing(db_session: Session) -> None:
    """После стоп-крана per-project live выключен → движок не публикует (needs_review)."""
    acc, project, _plan = _seed(db_session, "lamint-pause")
    _enable_readiness(db_session, acc.id, project.id)
    LiveAutopilotMonitoringService().pause_project_autopilot(
        db_session, project.id, confirmation="PAUSE_AUTOPILOT"
    )
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_published"] is False
    assert entry["auto_publish_blocked_reason"] == "live_readiness_blocked"
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "needs_review"


def test_worker_monitoring_disabled_by_default(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "lamint-worker-off")
    settings = Settings(scheduler_worker_enabled=True, scheduler_worker_dry_run=True)
    worker = SchedulerWorkerService(settings=settings)
    result = worker.tick(db_session, owner_id="w1", force=True)
    assert result.live_monitoring_enabled is False
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == 0


def test_worker_monitoring_preview_no_writes(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "lamint-worker-dry")
    settings = Settings(
        scheduler_worker_enabled=True,
        live_autopilot_monitoring_worker_enabled=True,
        live_autopilot_monitoring_dry_run=True,
    )
    worker = SchedulerWorkerService(settings=settings)
    result = worker.tick(db_session, owner_id="w2", force=True)
    assert result.live_monitoring_enabled is True
    assert result.live_monitoring_dry_run is True
    # Проект реально просканирован (иначе тест прошёл бы вхолостую)...
    assert result.live_monitoring_projects_scanned >= 1
    # ...но dry-run → снимки не пишутся.
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == 0
