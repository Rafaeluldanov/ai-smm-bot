"""Тесты режимов автоматизации в движке расписаний (v0.4.0).

Проверяют semi_auto/full_auto без реальных публикаций: live возможен ТОЛЬКО через
внедрённый fake-клиент в контролируемом тесте. По умолчанию (реальный реестр, live
выключен) авто-публикация всегда блокируется. Никакого ``publish-due``.
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


def _seed(
    db: Session,
    slug: str,
    mode: str = "semi_auto",
    auto_publish: bool = False,
    min_quality: int = 70,
    require_first: bool = True,
):  # noqa: ANN202
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
    plan.automation_mode = mode
    plan.auto_publish_enabled = auto_publish
    plan.min_quality_score_for_auto = min_quality
    plan.require_review_before_first_auto = require_first
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@x"}
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, plan


def _fake_publication() -> PostPublicationService:
    registry = PublicationPlatformRegistry(
        {
            "telegram": FakePublishingClient("telegram", live_enabled=True),
            "vk": FakePublishingClient("vk", live_enabled=True),
        }
    )
    return PostPublicationService(registry=registry, default_targets={"telegram": "@x"})


def test_semi_auto_creates_needs_review(db_session: Session) -> None:
    acc, project, _plan = _seed(db_session, "sm-semi", mode="semi_auto")
    svc = ScheduleAutomationService()
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["outcome"] == "draft_created"
    assert entry["auto_publish_attempted"] is False
    assert res["live_calls"] is False
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "needs_review"
    assert entry["quality_score"] is not None


def test_full_auto_low_score_blocks(db_session: Session) -> None:
    acc, project, _plan = _seed(
        db_session,
        "sm-lowq",
        mode="full_auto",
        auto_publish=True,
        min_quality=95,
        require_first=False,
    )
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_publish_blocked_reason"] == "quality_score_below_threshold"
    assert entry["auto_published"] is False
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "needs_review"


def test_full_auto_needs_first_review(db_session: Session) -> None:
    acc, project, _plan = _seed(
        db_session,
        "sm-first",
        mode="full_auto",
        auto_publish=True,
        min_quality=10,
        require_first=True,
    )
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    assert res["entries"][0]["auto_publish_blocked_reason"] == "needs_first_review"


def test_full_auto_live_disabled_does_not_publish(db_session: Session) -> None:
    """Реальный реестр (live выключен): авто-публикация блокируется как live_disabled."""
    acc, project, _plan = _seed(
        db_session,
        "sm-liveoff",
        mode="full_auto",
        auto_publish=True,
        min_quality=10,
        require_first=False,
    )
    svc = ScheduleAutomationService()  # реальный реестр, live выключен
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_publish_blocked_reason"] == "live_disabled"
    assert entry["auto_published"] is False
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "needs_review"


def test_full_auto_all_gates_publishes_with_fake_client(db_session: Session) -> None:
    acc, project, _plan = _seed(
        db_session,
        "sm-go",
        mode="full_auto",
        auto_publish=True,
        min_quality=10,
        require_first=False,
    )
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    res = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    entry = res["entries"][0]
    assert entry["auto_publish_blocked_reason"] is None
    assert entry["auto_published"] is True
    post = post_repository.get_post_by_id(db_session, entry["post_id"])
    assert post.status == "published"
    from app.repositories import post_feedback_repository

    counts = post_feedback_repository.aggregate_by_project(db_session, project.id)
    assert counts.get("auto_published") == 1


def test_full_auto_idempotent_no_duplicate(db_session: Session) -> None:
    acc, project, _plan = _seed(
        db_session,
        "sm-idem",
        mode="full_auto",
        auto_publish=True,
        min_quality=10,
        require_first=False,
    )
    svc = ScheduleAutomationService(publication_service=_fake_publication())
    first = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    second = svc.run_due(db_session, acc.id, project.id, _DATE, _NOW)
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["skipped"] == 1
