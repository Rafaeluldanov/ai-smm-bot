"""Интеграция live-readiness × schedule automation (v0.5.9, offline).

Ключевые инварианты безопасности:
- нельзя опубликовать при выключенном глобальном флаге (даже если project/platform live включены);
- нельзя опубликовать при выключенном project live или platform live;
- публикация возможна ТОЛЬКО когда все гейты true и внедрён fake-клиент (контролируемый тест);
- заблокированная публикация не списывает units;
- никакого publish_due.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
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
from app.services.platform_connection_service import PlatformConnectionService
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.schedule_automation_service import ScheduleAutomationService

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


def _enable_readiness(
    db: Session, account_id: int, project_id: int, *, project=True, platform=True
):
    pp = lrr.get_or_create_project_profile(db, account_id, project_id)
    lrr.update_project_profile(
        db,
        pp,
        {
            "status": "ready",
            "project_live_enabled": project,
            "full_auto_live_enabled": project,
        },
    )
    plat = lrr.get_or_create_platform_profile(db, account_id, project_id, "telegram")
    lrr.update_platform_profile(db, plat, {"status": "ready", "platform_live_enabled": platform})
    db.commit()


def test_cannot_publish_when_global_false(db_session: Session) -> None:
    """Реальный реестр (global off) → would_send false → блокировка (не publish)."""
    acc, project, _plan = _seed(db_session, "lri-global")
    _enable_readiness(db_session, acc.id, project.id)  # readiness ready, но global off
    svc = ScheduleAutomationService()  # реальный реестр, глобальные флаги false
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_published"] is False
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "needs_review"


def test_cannot_publish_when_project_live_disabled(db_session: Session) -> None:
    """Fake-клиент (global имитируется), но project live выключен → live_readiness_blocked."""
    acc, project, _plan = _seed(db_session, "lri-proj")
    _enable_readiness(db_session, acc.id, project.id, project=False, platform=True)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_published"] is False
    assert entry["auto_publish_blocked_reason"] == "live_readiness_blocked"


def test_cannot_publish_when_platform_live_disabled(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "lri-plat")
    _enable_readiness(db_session, acc.id, project.id, project=True, platform=False)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_published"] is False
    assert entry["auto_publish_blocked_reason"] == "live_readiness_blocked"


def test_publishes_only_with_all_gates_true(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "lri-go")
    _enable_readiness(db_session, acc.id, project.id, project=True, platform=True)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_published"] is True
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "published"


def test_blocked_publish_no_extra_debit(db_session: Session) -> None:
    """Заблокированная авто-публикация не списывает автопаблиш-units (только draft-генерацию)."""
    acc, project, _plan = _seed(db_session, "lri-nodebit")
    _enable_readiness(db_session, acc.id, project.id, project=False, platform=True)
    before = BillingService().get_balance(db_session, acc.id).balance_units
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    after = BillingService().get_balance(db_session, acc.id).balance_units
    # Списание только за генерацию draft (если было), но НЕ за автопубликацию (5 units).
    from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

    autopub_cost = BillingService().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION)
    assert before - after < autopub_cost + 1  # автопаблиш не списан
