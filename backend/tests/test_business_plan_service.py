"""Тесты AIBusinessPlannerService — генерация/approve/convert плана (v0.7.7, offline).

Инварианты:
- plan создаётся из цели (gap→стратегия→кварталы→KPI→вехи); confidence считается;
- approve только меняет статус; convert ТОЛЬКО при approved+подтверждении → draft workflow;
- convert не публикует/не включает live; tenant; аудит plan.*.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import (
    CONVERT_CONFIRMATION,
    AIBusinessPlannerError,
    AIBusinessPlannerService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIBusinessPlannerService:
    return AIBusinessPlannerService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _goal(db: Session, pid: int, uid: int | None = None) -> int:
    return _svc().create_business_goal(
        db,
        pid,
        goal_type="revenue",
        title="Выручка x5",
        target_value=5000000,
        current_value=1000000,
        user_id=uid,
    )["id"]


def test_generate_plan(db_session: Session) -> None:
    pid, uid = _project(db_session, "plan1")
    svc = _svc()
    gid = _goal(db_session, pid, uid)
    out = svc.generate_strategic_plan(db_session, gid, user_id=uid)
    plan = out["plan"]
    assert plan["status"] == "generated"
    assert plan["gap_analysis"]["gap"] == 4000000.0
    assert 0.0 <= plan["confidence_score"] <= 100.0
    assert len(out["objectives"]) == 4
    assert all(o["quarter"] in ("Q1", "Q2", "Q3", "Q4") for o in out["objectives"])
    assert all(len(o["milestones"]) == 2 for o in out["objectives"])


def test_plan_confidence_formula(db_session: Session) -> None:
    svc = _svc()
    c = svc.calculate_plan_confidence(
        forecast_confidence=70, data_quality=80, strategy_confidence=60
    )
    assert c == round(0.4 * 70 + 0.3 * 80 + 0.3 * 60, 1)


def test_regenerate_does_not_multiply_objectives(db_session: Session) -> None:
    """Повторная генерация плана не размножает кварталы (пересоздание)."""
    pid, _ = _project(db_session, "plan2")
    svc = _svc()
    gid = _goal(db_session, pid)
    p1 = svc.generate_strategic_plan(db_session, gid)
    # регенерация квартальных целей того же плана
    svc.generate_quarter_objectives(db_session, p1["plan"]["id"])
    objectives = svc.get_objectives(db_session, p1["plan"]["id"])
    assert len(objectives) == 4
    # вехи пересоздаются, а не накапливаются (ровно 2 на цель).
    assert all(len(o["milestones"]) == 2 for o in objectives)


def test_approve_then_convert_creates_draft_only(db_session: Session) -> None:
    from app.models.business_workflow import BusinessWorkflow
    from app.models.post_publication import PostPublication

    pid, uid = _project(db_session, "plan3")
    svc = _svc()
    gid = _goal(db_session, pid, uid)
    plan = svc.generate_strategic_plan(db_session, gid, user_id=uid)["plan"]
    pid_plan = plan["id"]
    # convert до approve запрещён
    with pytest.raises(AIBusinessPlannerError):
        svc.convert_to_workflow(db_session, pid_plan, confirmation=CONVERT_CONFIRMATION)
    svc.approve_plan(db_session, pid_plan, user_id=uid)
    # без подтверждения запрещён
    with pytest.raises(AIBusinessPlannerError):
        svc.convert_to_workflow(db_session, pid_plan, confirmation="")
    res = svc.convert_to_workflow(
        db_session, pid_plan, confirmation=CONVERT_CONFIRMATION, user_id=uid
    )
    assert res["live_enabled"] is False
    wfs = db_session.query(BusinessWorkflow).filter_by(project_id=pid).all()
    assert len(wfs) == 1 and wfs[0].status == "draft"
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_approve_requires_generated(db_session: Session) -> None:
    """approve нельзя из draft/archived — только из generated/reviewed."""
    pid, _ = _project(db_session, "plan4")
    svc = _svc()
    gid = _goal(db_session, pid)
    plan = svc.generate_strategic_plan(db_session, gid)["plan"]
    svc.approve_plan(db_session, plan["id"])
    # повторный approve из approved запрещён
    with pytest.raises(AIBusinessPlannerError):
        svc.approve_plan(db_session, plan["id"])


def test_explain_plan_mentions_advisory(db_session: Session) -> None:
    pid, _ = _project(db_session, "plan5")
    svc = _svc()
    gid = _goal(db_session, pid)
    plan = svc.generate_strategic_plan(db_session, gid)["plan"]
    exp = svc.explain_plan(db_session, plan["id"])
    joined = " ".join(exp["reasons"]).lower()
    assert "одобрен" in joined or "рекомендац" in joined


def test_audit_plan_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "plan6")
    svc = _svc()
    gid = _goal(db_session, pid, uid)
    plan = svc.generate_strategic_plan(db_session, gid, user_id=uid)["plan"]
    svc.approve_plan(db_session, plan["id"], user_id=uid)
    svc.convert_to_workflow(db_session, plan["id"], confirmation=CONVERT_CONFIRMATION, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "goal.created",
        "plan.generated",
        "objective.created",
        "milestone.created",
        "plan.approved",
        "workflow.draft_created",
    ):
        assert expected in actions


def test_missing_plan_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIBusinessPlannerError, match="не найден"):
        _svc().get_plan(db_session, 999999)
