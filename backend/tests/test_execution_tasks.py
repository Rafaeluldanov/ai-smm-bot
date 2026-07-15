"""Тесты задач/владельцев/блокеров — AI Execution Coordinator (v0.7.8, offline).

Инварианты:
- assign меняет owner + status (pending→assigned); чужой владелец отклоняется;
- set_task_status меняет только статус; блокеры: overdue/no_owner/no_progress/dependency/blocked;
- рекомендации формируются из блокеров.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import execution_repository as repo
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


def _generated(db: Session, slug: str) -> tuple[int, int, int, list[dict]]:
    pid, uid = _project(db, slug)
    pl = AIBusinessPlannerService(settings=_SETTINGS)
    gid = pl.create_business_goal(
        db, pid, goal_type="revenue", title="x5", target_value=5000000, current_value=1000000
    )["id"]
    sp = pl.generate_strategic_plan(db, gid)["plan"]["id"]
    pl.approve_plan(db, sp)
    svc = _svc()
    ep = svc.create_execution_plan(db, pid, strategic_plan_id=sp)["id"]
    out = svc.generate_execution(db, ep)
    tasks = [t for o in out["objectives"] for t in o["tasks"]]
    return pid, uid, ep, tasks


def test_three_tasks_per_objective(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk1")
    assert len(tasks) == 12
    assert all(t["status"] == "pending" and t["owner_user_id"] is None for t in tasks)


def test_assign_owner_sets_status(db_session: Session) -> None:
    _pid, uid, ep, tasks = _generated(db_session, "extk2")
    out = _svc().assign_owner(db_session, tasks[0]["id"], uid)
    assert out["owner_user_id"] == uid and out["status"] == "assigned"


def test_assign_foreign_owner_rejected(db_session: Session) -> None:
    """Владелец из другого аккаунта отклоняется (tenant isolation)."""
    _pid, _uid, ep, tasks = _generated(db_session, "extk3")
    _pid2, uid2 = _project(db_session, "extk3b")  # чужой пользователь/аккаунт
    with pytest.raises(AIExecutionCoordinatorError):
        _svc().assign_owner(db_session, tasks[0]["id"], uid2)


def test_set_status_and_unknown_rejected(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk4")
    svc = _svc()
    out = svc.set_task_status(db_session, tasks[0]["id"], "in_progress")
    assert out["status"] == "in_progress"
    with pytest.raises(AIExecutionCoordinatorError):
        svc.set_task_status(db_session, tasks[0]["id"], "bogus")


def test_overdue_blocker(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk5")
    task = repo.get_task(db_session, tasks[0]["id"])
    task.deadline = datetime.now(UTC) - timedelta(days=2)  # просрочен
    db_session.commit()
    blockers = _svc().detect_blockers(db_session, ep)
    assert any(b["type"] == "overdue" and b["task_id"] == tasks[0]["id"] for b in blockers)


def test_no_owner_blocker_after_days(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk6")
    task = repo.get_task(db_session, tasks[0]["id"])
    task.created_at = datetime.now(UTC) - timedelta(days=10)  # старая задача без владельца
    db_session.commit()
    blockers = _svc().detect_blockers(db_session, ep)
    assert any(b["type"] == "no_owner" and b["task_id"] == tasks[0]["id"] for b in blockers)


def test_dependency_blocker(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk7")
    # task[1] зависит от task[0] (не завершена) → dependency-блокер
    repo.create_dependency(
        db_session,
        task_id=tasks[1]["id"],
        depends_on_task_id=tasks[0]["id"],
        dependency_type="task",
        status="pending",
    )
    blockers = _svc().detect_blockers(db_session, ep)
    assert any(b["type"] == "dependency" and b["task_id"] == tasks[1]["id"] for b in blockers)


def test_dependency_satisfied_when_dep_completed(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk8")
    repo.create_dependency(
        db_session, task_id=tasks[1]["id"], depends_on_task_id=tasks[0]["id"], status="pending"
    )
    _svc().complete_task(db_session, tasks[0]["id"])  # предшественник завершён
    blockers = _svc().detect_blockers(db_session, ep)
    assert not any(b["type"] == "dependency" and b["task_id"] == tasks[1]["id"] for b in blockers)


def test_recommendations_from_blockers(db_session: Session) -> None:
    _pid, _uid, ep, tasks = _generated(db_session, "extk9")
    task = repo.get_task(db_session, tasks[0]["id"])
    task.created_at = datetime.now(UTC) - timedelta(days=10)
    db_session.commit()
    recs = _svc().generate_coordination_recommendations(db_session, ep)
    assert any("ответственн" in r.lower() for r in recs)


def test_no_blockers_clean_plan(db_session: Session) -> None:
    _pid, _uid, ep, _tasks = _generated(db_session, "extk10")
    recs = _svc().generate_coordination_recommendations(db_session, ep)
    assert any("по плану" in r.lower() for r in recs)


def test_blocker_detected_audit_exactly_once(db_session: Session) -> None:
    """detect_blockers пишет РОВНО один execution.blocker_detected при находках (не 0 и не 2)."""
    from app.models.audit_log import AuditLogEntry

    pid, _uid, ep, tasks = _generated(db_session, "extk11")
    task = repo.get_task(db_session, tasks[0]["id"])
    task.deadline = datetime.now(UTC) - timedelta(days=2)  # overdue → блокер
    db_session.commit()
    _svc().detect_blockers(db_session, ep)
    entries = [
        e
        for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()
        if e.action == "execution.blocker_detected"
    ]
    assert len(entries) == 1


def test_health_audits_blocker_once(db_session: Session) -> None:
    """get_health вычисляет блокеры один раз → ровно один execution.blocker_detected (не 2)."""
    from app.models.audit_log import AuditLogEntry

    pid, _uid, ep, tasks = _generated(db_session, "extk12")
    task = repo.get_task(db_session, tasks[0]["id"])
    task.deadline = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    _svc().get_health(db_session, ep)
    entries = [
        e
        for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()
        if e.action == "execution.blocker_detected"
    ]
    assert len(entries) == 1  # не 2 (двойного detect_blockers быть не должно)
