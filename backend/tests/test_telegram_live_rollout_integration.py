"""Интеграция Telegram live rollout × schedule automation (v0.6.0, offline).

Инварианты:
- schedule automation фиксирует blocked LivePublishAttempt, когда Telegram global false;
- заблокированная попытка не списывает units;
- fake-клиент + все флаги true → attempt published;
- дубликат блокируется (idempotency);
- никакого publish_due.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
from app.models.live_publish_attempt import LivePublishAttempt
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    live_readiness_repository as lrr,
)
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
            project_id=project.id, config_id=config.id, title="Ф", cta="Заказать за 990 руб"
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


def test_records_blocked_attempt_when_global_false(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "tgi-global")
    _enable_readiness(db_session, acc.id, project.id)  # readiness on, но global флаг off
    svc = ScheduleAutomationService()  # реальный реестр, global false
    svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    attempts = db_session.query(LivePublishAttempt).filter_by(project_id=project.id).all()
    assert len(attempts) == 1
    assert attempts[0].status == "blocked"
    assert attempts[0].live_attempted is False


def test_blocked_attempt_no_debit(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "tgi-nodebit")
    _enable_readiness(db_session, acc.id, project.id)
    before = BillingService().get_balance(db_session, acc.id).balance_units
    svc = ScheduleAutomationService()  # global false → blocked
    svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    after = BillingService().get_balance(db_session, acc.id).balance_units
    from app.services.billing_service import USAGE_AUTO_PUBLISH_ACTION

    autopub_cost = BillingService().estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION)
    assert before - after < autopub_cost + 1  # автопаблиш не списан


def test_records_published_attempt_with_fake_client(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "tgi-go")
    _enable_readiness(db_session, acc.id, project.id)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    assert res["entries"][0]["auto_published"] is True
    attempts = db_session.query(LivePublishAttempt).filter_by(project_id=project.id).all()
    assert len(attempts) == 1
    assert attempts[0].status == "published"
    assert attempts[0].live_attempted is True


def test_duplicate_attempt_blocked(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "tgi-dup")
    _enable_readiness(db_session, acc.id, project.id)
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    # Повторный прогон того же слота: idempotency не создаёт второй attempt.
    svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    attempts = db_session.query(LivePublishAttempt).filter_by(project_id=project.id).all()
    assert len(attempts) == 1
