"""Тесты сервиса Calendar Assistant (v0.5.8, offline).

Построение календаря, риски, оценки, dry-run без записи, создание/применение (создаёт
CrmPublishingPlan), пауза/возобновление. Без live-публикаций, без изменения live-флагов.
"""

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.autopilot_calendar_plan import AutopilotCalendarPlan
from app.models.crm_bot_smm import CrmPublishingPlan
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.autopilot_calendar_assistant_service import (
    AutopilotCalendarAssistantService,
    get_autopilot_calendar_assistant_service,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc() -> AutopilotCalendarAssistantService:
    return get_autopilot_calendar_assistant_service()


def test_build_presets(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-pre")
    presets = _svc().build_calendar_presets(db_session, project.id)
    assert len(presets) == 8
    keys = {p["preset"] for p in presets}
    assert {"daily", "weekdays", "three_per_week", "two_per_week"} <= keys
    for p in presets:
        assert p["estimated_posts_per_month"] >= 0


def test_recommend(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-rec")
    rec = _svc().recommend_calendar(db_session, project.id)
    assert rec["recommended_preset"]
    assert 0.0 <= rec["confidence_score"] <= 1.0


def test_preview_no_writes(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-prev")
    before = db_session.query(AutopilotCalendarPlan).count()
    prev = _svc().preview_calendar(
        db_session, project.id, {"preset": "three_per_week", "goal": "mixed"}
    )
    assert prev["writes"] is False
    assert prev["weekdays"] == [0, 2, 4]
    assert "risks" in prev and "estimates" in prev
    assert db_session.query(AutopilotCalendarPlan).count() == before


def test_create_dry_run_no_writes(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-dry")
    before = db_session.query(AutopilotCalendarPlan).count()
    res = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "two_per_week"}, dry_run=True
    )
    assert res["dry_run"] is True
    assert db_session.query(AutopilotCalendarPlan).count() == before


def test_create_and_apply_creates_publishing_plan(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-apply")
    created = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "two_per_week", "goal": "leads"}, dry_run=False
    )
    assert created["ok"] is True
    assert created["status"] == "draft"
    # two_per_week => weekdays [1, 4] сохраняются точно (frequency=custom при применении).
    assert created["weekdays"] == [1, 4]

    applied = _svc().apply_calendar_to_project(db_session, project.id, created["id"])
    assert applied["ok"] is True
    assert applied["live_publish"] is False
    assert applied["status"] == "active"
    assert applied["publishing_plan_id"]

    plans = db_session.query(CrmPublishingPlan).all()
    assert len(plans) == 1
    assert plans[0].weekdays == [1, 4]


def test_apply_links_publishing_plan(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-link")
    created = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "daily"}, dry_run=False
    )
    applied = _svc().apply_calendar_to_project(db_session, project.id, created["id"])
    plan = db_session.get(AutopilotCalendarPlan, created["id"])
    assert applied["publishing_plan_id"] in (plan.linked_publishing_plan_ids or [])
    assert plan.status == "active"


def test_pause_resume(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-pr")
    created = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "daily"}, dry_run=False
    )
    _svc().apply_calendar_to_project(db_session, project.id, created["id"])
    paused = _svc().pause_calendar(db_session, project.id)
    assert paused["status"] == "paused"
    resumed = _svc().resume_calendar(db_session, project.id)
    assert resumed["status"] == "active"


def test_dashboard(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-dash")
    created = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "daily"}, dry_run=False
    )
    _svc().apply_calendar_to_project(db_session, project.id, created["id"])
    dash = _svc().build_calendar_dashboard(db_session, project.id)
    assert dash["has_active_plan"] is True
    assert dash["active_plan"]["preset"] == "daily"
    assert "next_best_action" in dash and "presets" in dash


def test_apply_does_not_flip_live_flags(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "cas-live")
    created = _svc().create_calendar_plan(
        db_session, project.id, {"preset": "daily", "platforms": ["telegram"]}, dry_run=False
    )
    _svc().apply_calendar_to_project(db_session, project.id, created["id"])
    s = get_settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
