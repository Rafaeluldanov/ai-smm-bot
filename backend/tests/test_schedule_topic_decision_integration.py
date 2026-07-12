"""Тесты интеграции автовыбора темы в движок расписаний (v0.4.4).

Offline; никаких live-публикаций. Проверяют, что run_due пишет метаданные решения в
generation_notes и ScheduleRun.run_metadata, fallback при выключенном флаге, low_confidence.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post import Post
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    schedule_topic_decision_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.schedule_automation_service import ScheduleAutomationService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)  # понедельник 13:00
_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры"]


def _seed(db: Session, slug: str = "int"):  # noqa: ANN202
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
    learn = ClientLearningService()
    for t in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=t,
                status="needs_review",
                vk_text="T",
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return account, project


def _svc(**flags: object) -> ScheduleAutomationService:
    return ScheduleAutomationService(settings=Settings(**flags))


def test_disabled_flag_no_decision_but_draft(db_session: Session) -> None:
    acc, project = _seed(db_session, "int-off")
    # Флаг выключен (default) → обычный CRM-драфт, решений нет.
    result = _svc().run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["created"] == 1
    assert result["topic_decisions_created"] == 0
    assert schedule_topic_decision_repository.list_for_project(db_session, project.id) == []


def test_run_creates_decision_metadata(db_session: Session) -> None:
    acc, project = _seed(db_session, "int-on")
    result = _svc(
        auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False
    ).run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["created"] == 1
    assert result["topic_decisions_created"] == 1
    rows = schedule_topic_decision_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1 and rows[0].status == "draft_created"
    # generation_notes драфта несёт решение.
    draft = (
        db_session.query(Post)
        .filter(Post.project_id == project.id, Post.status == "needs_review")
        .order_by(Post.id.desc())
        .first()
    )
    notes = draft.generation_notes or {}
    assert notes.get("schedule_topic_decision_id") == rows[0].id
    assert notes.get("selected_topic")


def test_low_confidence_flag_and_needs_review(db_session: Session) -> None:
    # Проект без обучения → низкая уверенность → решение с low_confidence, пост needs_review.
    user = user_repository.create_user(db_session, email="lc@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="lc", slug="lc", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="lc", slug="lc-proj")
    )
    project.account_id = account.id
    db_session.commit()
    cfg = crm.create_config(
        db_session, CrmBotProjectConfigCreate(project_id=project.id, display_name="lc")
    )
    cat = crm.create_category(
        db_session,
        CrmPromotionCategoryCreate(
            project_id=project.id, config_id=cfg.id, title="Разное", cta="CTA"
        ),
    )
    crm.create_plan(
        db_session,
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
        db_session, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
    )
    BillingService().manual_topup(db_session, account.id, 500, idempotency_key="lc")
    result = _svc(
        auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False
    ).run_due(db_session, account.id, project.id, now=_NOW)
    assert result["topic_decisions_created"] == 1
    assert result["low_confidence_decisions"] == 1
    rows = schedule_topic_decision_repository.list_for_project(db_session, project.id)
    assert "low_confidence" in (rows[0].risk_flags or [])
    draft = (
        db_session.query(Post)
        .filter(Post.project_id == project.id)
        .order_by(Post.id.desc())
        .first()
    )
    assert draft.status == "needs_review"


def test_no_live_publish(db_session: Session) -> None:
    acc, project = _seed(db_session, "int-nolive")
    from app.models.post_publication import PostPublication

    _svc(auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False).run_due(
        db_session, acc.id, project.id, now=_NOW
    )
    assert db_session.query(Post).filter(Post.status == "published").count() == 0
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"


def test_full_auto_still_gated_with_decision(db_session: Session) -> None:
    # full_auto + auto_publish, но live выключен → пост остаётся needs_review, решение есть.
    acc, project = _seed(db_session, "int-fa")
    from app.repositories import crm_bot_smm_repository as crm_repo

    config = crm_repo.get_config_by_project_id(db_session, project.id)
    plan = crm_repo.list_plans_by_config(db_session, config.id)[0]
    plan.automation_mode = "full_auto"
    plan.auto_publish_enabled = True
    plan.require_review_before_first_auto = False
    plan.min_quality_score_for_auto = 0
    db_session.commit()
    result = _svc(
        auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False
    ).run_due(db_session, acc.id, project.id, now=_NOW)
    assert result["topic_decisions_created"] == 1
    # Live выключен → авто-публикация заблокирована, пост needs_review, ничего не published.
    assert db_session.query(Post).filter(Post.status == "published").count() == 0
    draft = (
        db_session.query(Post)
        .filter(Post.project_id == project.id)
        .order_by(Post.id.desc())
        .first()
    )
    assert draft.status == "needs_review"


def test_run_metadata_has_decision(db_session: Session) -> None:
    acc, project = _seed(db_session, "int-meta")
    from app.repositories import schedule_run_repository

    _svc(auto_topic_selection_worker_enabled=True, auto_topic_selection_dry_run=False).run_due(
        db_session, acc.id, project.id, now=_NOW
    )
    runs = schedule_run_repository.list_for_project(db_session, project.id)
    assert runs
    meta = runs[0].run_metadata or {}
    assert "topic_decision" in meta
    assert meta["topic_decision"].get("selected_topic")
