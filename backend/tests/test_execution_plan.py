"""Тесты планов исполнения — AI Execution Coordinator (v0.7.8, offline).

Инварианты:
- execution plan создаётся ТОЛЬКО из одобренного стратегического плана; не-approved/чужой — отказ;
- list/summary; tenant isolation; аудит execution.created; missing → 404.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_execution_coordinator_service import (
    AIExecutionCoordinatorError,
    AIExecutionCoordinatorService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIExecutionCoordinatorService:
    return AIExecutionCoordinatorService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _strategic_plan(db: Session, pid: int, *, approve: bool = True) -> int:
    pl = AIBusinessPlannerService(settings=_SETTINGS)
    gid = pl.create_business_goal(
        db, pid, goal_type="revenue", title="x5", target_value=5000000, current_value=1000000
    )["id"]
    plan = pl.generate_strategic_plan(db, gid)["plan"]
    if approve:
        pl.approve_plan(db, plan["id"])
    return plan["id"]


def test_create_from_approved_plan(db_session: Session) -> None:
    pid, uid = _project(db_session, "exp1")
    sp = _strategic_plan(db_session, pid, approve=True)
    ep = _svc().create_execution_plan(db_session, pid, strategic_plan_id=sp, user_id=uid)
    assert ep["status"] == "draft"
    assert ep["strategic_plan_id"] == sp


def test_create_rejects_not_approved_plan(db_session: Session) -> None:
    pid, _ = _project(db_session, "exp2")
    sp = _strategic_plan(db_session, pid, approve=False)  # generated, not approved
    with pytest.raises(AIExecutionCoordinatorError, match="одобр"):
        _svc().create_execution_plan(db_session, pid, strategic_plan_id=sp)


def test_create_rejects_foreign_plan(db_session: Session) -> None:
    pid1, _ = _project(db_session, "exp3a")
    pid2, _ = _project(db_session, "exp3b")
    sp = _strategic_plan(db_session, pid1, approve=True)
    with pytest.raises(AIExecutionCoordinatorError):
        _svc().create_execution_plan(db_session, pid2, strategic_plan_id=sp)


def test_create_rejects_missing_plan(db_session: Session) -> None:
    pid, _ = _project(db_session, "exp4")
    with pytest.raises(AIExecutionCoordinatorError, match="не найден"):
        _svc().create_execution_plan(db_session, pid, strategic_plan_id=999999)


def test_list_and_summary(db_session: Session) -> None:
    pid, _ = _project(db_session, "exp5")
    sp = _strategic_plan(db_session, pid, approve=True)
    svc = _svc()
    svc.create_execution_plan(db_session, pid, strategic_plan_id=sp)
    assert len(svc.list_execution_plans(db_session, pid)) == 1
    summary = svc.get_summary(db_session, pid)
    assert summary["plans_total"] == 1


def test_audit_execution_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "exp6")
    sp = _strategic_plan(db_session, pid, approve=True)
    _svc().create_execution_plan(db_session, pid, strategic_plan_id=sp, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "execution.created" in actions


def test_missing_plan_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIExecutionCoordinatorError, match="не найден"):
        _svc().get_execution_plan(db_session, 999999)
