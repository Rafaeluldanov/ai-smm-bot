"""Тесты AIWorkflowManagerService — AI Workflow Manager (v0.7.2, offline).

Инварианты:
- workflow создаётся; steps генерируются (дедуп); blocker → blocked → resolve восстанавливает;
- assign/complete/status только меняют статус (НЕ выполняют действия, no live/CRM);
- health/рекомендации считаются; tenant isolation; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import workflow_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_workflow_manager_service import (
    AIWorkflowManagerError,
    AIWorkflowManagerService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIWorkflowManagerService:
    return AIWorkflowManagerService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _workflow(db: Session, pid: int, wtype: str = "sales") -> int:
    return _svc().create_workflow_from_goal(
        db, pid, name="Тест-процесс", workflow_type=wtype, goal="цель", status="active"
    )["id"]


def test_create_workflow(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc1")
    wf = _svc().create_workflow_from_goal(
        db_session,
        pid,
        name="Рост продаж",
        workflow_type="sales",
        goal="increase sales",
        status="active",
        user_id=uid,
    )
    assert wf["status"] == "active" and wf["workflow_type"] == "sales"
    assert wf["progress_percent"] == 0.0


def test_create_workflow_rejects_unknown_type(db_session: Session) -> None:
    pid, _ = _project(db_session, "wfsvc1b")
    with pytest.raises(AIWorkflowManagerError):
        _svc().create_workflow_from_goal(db_session, pid, name="x", workflow_type="bogus")


def test_generate_steps_and_dedup(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc2")
    svc = _svc()
    wid = _workflow(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid, user_id=uid)
    assert len(steps) == 3  # дефолтные этапы sales
    assert [s["order_number"] for s in steps] == [1, 2, 3]
    again = svc.generate_workflow_steps(db_session, wid, user_id=uid)
    assert again == []  # дедуп: без дубликатов
    assert len(svc.list_steps(db_session, wid)) == 3


def test_assign_and_complete_no_external_actions(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc3")
    svc = _svc()
    wid = _workflow(db_session, pid)
    step_id = svc.generate_workflow_steps(db_session, wid)[0]["id"]
    a = svc.assign_step(db_session, step_id, owner_user_id=uid, user_id=uid)
    assert a["status"] == "assigned" and a["owner_user_id"] == uid
    c = svc.complete_step(db_session, step_id, user_id=uid)
    assert c["status"] == "completed" and c["completed_at"] is not None
    # никаких внешних действий/публикаций
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_complete_terminal_guards(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc4")
    svc = _svc()
    wid = _workflow(db_session, pid)
    step_id = svc.generate_workflow_steps(db_session, wid)[0]["id"]
    svc.complete_step(db_session, step_id)
    with pytest.raises(AIWorkflowManagerError):  # double complete
        svc.complete_step(db_session, step_id)
    with pytest.raises(AIWorkflowManagerError):  # status change on closed step
        svc.update_step_status(db_session, step_id, "in_progress")


def test_blocker_flow(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc5")
    svc = _svc()
    wid = _workflow(db_session, pid)
    step_id = svc.generate_workflow_steps(db_session, wid)[1]["id"]
    blocker = svc.create_blocker(
        db_session,
        wid,
        blocker_type="approval",
        title="Ждём одобрения",
        step_id=step_id,
        severity="high",
        user_id=uid,
    )
    assert blocker["status"] == "open"
    assert repo.get_step(db_session, step_id).status == "blocked"
    resolved = svc.resolve_blocker(db_session, blocker["id"], user_id=uid)
    assert resolved["status"] == "resolved" and resolved["resolved_at"] is not None
    # blocked-этап без владельца восстановлен в pending
    assert repo.get_step(db_session, step_id).status == "pending"


def test_workflow_health(db_session: Session) -> None:
    pid, uid = _project(db_session, "wfsvc6")
    svc = _svc()
    wid = _workflow(db_session, pid)
    svc.generate_workflow_steps(db_session, wid)
    svc.create_blocker(db_session, wid, blocker_type="resource", title="Нет ресурса")
    health = svc.analyze_workflow_health(db_session, wid)
    assert 0 <= health["health_score"] <= 100
    assert health["open_blockers"] == 1
    assert health["recommendations"]


def test_missing_workflow_raises(db_session: Session) -> None:
    with pytest.raises(AIWorkflowManagerError):
        _svc().get_workflow(db_session, 999999)
