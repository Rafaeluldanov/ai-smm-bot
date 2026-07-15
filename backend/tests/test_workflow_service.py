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


def test_resolve_keeps_step_blocked_if_other_open_blocker(db_session: Session) -> None:
    """resolve одного блокера не разблокирует этап, пока есть другой открытый блокер на нём;
    снятие последнего блокера действительно разблокирует."""
    pid, uid = _project(db_session, "wfsvc7")
    svc = _svc()
    wid = _workflow(db_session, pid)
    sid = svc.generate_workflow_steps(db_session, wid)[0]["id"]
    a = svc.create_blocker(db_session, wid, blocker_type="dependency", title="A", step_id=sid)
    b = svc.create_blocker(db_session, wid, blocker_type="resource", title="B", step_id=sid)
    assert repo.get_step(db_session, sid).status == "blocked"
    svc.resolve_blocker(db_session, a["id"])
    # второй блокер ещё открыт → этап остаётся blocked
    assert repo.get_step(db_session, sid).status == "blocked"
    # снятие ВТОРОГО (последнего) блокера действительно разблокирует этап
    svc.resolve_blocker(db_session, b["id"])
    assert repo.get_step(db_session, sid).status == "pending"


def test_resolve_blocker_is_step_scoped(db_session: Session) -> None:
    """Открытый блокер на ДРУГОМ этапе не мешает разблокировать этот (step-scoped guard)."""
    pid, uid = _project(db_session, "wfsvc7b")
    svc = _svc()
    wid = _workflow(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)
    s1, s2 = steps[0]["id"], steps[1]["id"]
    svc.create_blocker(db_session, wid, blocker_type="dependency", title="X", step_id=s1)
    by = svc.create_blocker(db_session, wid, blocker_type="resource", title="Y", step_id=s2)
    assert repo.get_step(db_session, s1).status == "blocked"
    assert repo.get_step(db_session, s2).status == "blocked"
    svc.resolve_blocker(db_session, by["id"])
    # S2 разблокирован; открытый блокер на S1 к нему не относится
    assert repo.get_step(db_session, s2).status == "pending"
    assert repo.get_step(db_session, s1).status == "blocked"


def test_resolve_restores_owned_step_to_assigned(db_session: Session) -> None:
    """Снятие блокера с назначенного этапа возвращает его в assigned (не pending)."""
    pid, uid = _project(db_session, "wfsvc8")
    svc = _svc()
    wid = _workflow(db_session, pid)
    sid = svc.generate_workflow_steps(db_session, wid)[0]["id"]
    svc.assign_step(db_session, sid, owner_user_id=uid)
    b = svc.create_blocker(db_session, wid, blocker_type="approval", title="A", step_id=sid)
    svc.resolve_blocker(db_session, b["id"])
    step = repo.get_step(db_session, sid)
    assert step.status == "assigned" and step.owner_user_id == uid


def test_workflow_from_objective_and_task(db_session: Session) -> None:
    """Создание процесса из бизнес-цели/AI-задачи обогащает поля и метит источник."""
    from app.repositories import business_os_repository, chief_of_staff_repository

    pid, uid = _project(db_session, "wfsvc9")
    svc = _svc()
    obj = business_os_repository.create_objective(
        db_session,
        project_id=pid,
        account_id=None,
        type="revenue_growth",
        title="Вырасти x2",
        target_value=200000,
    )
    wf = svc.create_workflow_from_goal(
        db_session, pid, name="", workflow_type="growth", objective_id=obj.id
    )
    assert wf["name"] and wf["target_value"] == 200000
    w_meta = repo.get_workflow(db_session, wf["id"]).workflow_metadata
    assert w_meta.get("source_objective_id") == obj.id
    task = chief_of_staff_repository.create_task(
        db_session,
        project_id=pid,
        account_id=None,
        briefing_id=None,
        task_type="content",
        title="Сделать кейсы",
    )
    wf2 = svc.create_workflow_from_goal(
        db_session, pid, name="", workflow_type="content", task_id=task.id
    )
    assert "кейсы" in wf2["name"].lower()
    w2_meta = repo.get_workflow(db_session, wf2["id"]).workflow_metadata
    assert w2_meta.get("source_task_id") == task.id


def test_workflow_from_foreign_objective_rejected(db_session: Session) -> None:
    """Нельзя создать процесс проекта P2 из цели чужого проекта P1 (tenant isolation)."""
    from app.repositories import business_os_repository

    p1, _ = _project(db_session, "wff1")
    p2, _ = _project(db_session, "wff2")
    obj = business_os_repository.create_objective(
        db_session, project_id=p1, account_id=None, type="revenue_growth", title="P1"
    )
    with pytest.raises(AIWorkflowManagerError):
        _svc().create_workflow_from_goal(
            db_session, p2, name="x", workflow_type="growth", objective_id=obj.id
        )


def test_audit_entries_written(db_session: Session) -> None:
    """create/step/assign/complete/blocker/resolve пишут workflow.* в AuditLog."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "wfsvc10")
    svc = _svc()
    wid = _workflow(db_session, pid)
    sid = svc.generate_workflow_steps(db_session, wid, user_id=uid)[0]["id"]
    svc.assign_step(db_session, sid, owner_user_id=uid, user_id=uid)
    svc.complete_step(db_session, sid, user_id=uid)
    b = svc.create_blocker(db_session, wid, blocker_type="resource", title="b", user_id=uid)
    svc.resolve_blocker(db_session, b["id"], user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "workflow.created",
        "workflow.step_created",
        "workflow.step_assigned",
        "workflow.step_completed",
        "workflow.blocker_created",
        "workflow.blocker_resolved",
    ):
        assert expected in actions


def test_assign_and_cancelled_step_guards(db_session: Session) -> None:
    """assign/complete/status запрещены на закрытых (cancelled/completed) этапах."""
    pid, uid = _project(db_session, "wfsvc11")
    svc = _svc()
    wid = _workflow(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)
    cancelled, completed = steps[0]["id"], steps[1]["id"]
    svc.update_step_status(db_session, cancelled, "cancelled")
    for act in (
        lambda: svc.assign_step(db_session, cancelled, owner_user_id=uid),
        lambda: svc.complete_step(db_session, cancelled),
        lambda: svc.update_step_status(db_session, cancelled, "in_progress"),
    ):
        with pytest.raises(AIWorkflowManagerError):
            act()
    svc.complete_step(db_session, completed)
    with pytest.raises(AIWorkflowManagerError):  # assign закрытого completed
        svc.assign_step(db_session, completed, owner_user_id=uid)


def test_double_resolve_blocker_blocked(db_session: Session) -> None:
    """Повторное снятие блокера запрещено."""
    pid, uid = _project(db_session, "wfsvc12")
    svc = _svc()
    wid = _workflow(db_session, pid)
    b = svc.create_blocker(db_session, wid, blocker_type="external", title="b")
    svc.resolve_blocker(db_session, b["id"])
    with pytest.raises(AIWorkflowManagerError):
        svc.resolve_blocker(db_session, b["id"])


def test_blocker_foreign_step_rejected(db_session: Session) -> None:
    """Блокер нельзя привязать к этапу ЧУЖОГО процесса."""
    pid, uid = _project(db_session, "wfsvc13")
    svc = _svc()
    w1 = _workflow(db_session, pid)
    w2 = _workflow(db_session, pid)
    step_of_w2 = svc.generate_workflow_steps(db_session, w2)[0]["id"]
    with pytest.raises(AIWorkflowManagerError):
        svc.create_blocker(db_session, w1, blocker_type="dependency", title="x", step_id=step_of_w2)


def test_create_rejects_unknown_status_and_empty_name(db_session: Session) -> None:
    """create_workflow_from_goal отклоняет неизвестный статус и пустое имя без источника."""
    pid, _ = _project(db_session, "wfsvc14")
    with pytest.raises(AIWorkflowManagerError):
        _svc().create_workflow_from_goal(
            db_session, pid, name="x", workflow_type="growth", status="bogus"
        )
    with pytest.raises(AIWorkflowManagerError):
        _svc().create_workflow_from_goal(db_session, pid, name="   ", workflow_type="growth")


def test_generate_steps_disabled_returns_empty(db_session: Session) -> None:
    """При выключенном workflow_manager генерация этапов возвращает [] и ничего не пишет."""
    from app.config import Settings

    pid, _ = _project(db_session, "wfsvc15")
    svc = _svc()
    wid = _workflow(db_session, pid)
    off_settings = Settings(
        media_proxy_public_base_url="https://m.example.com", workflow_manager_enabled=False
    )
    off = AIWorkflowManagerService(settings=off_settings)
    assert off.generate_workflow_steps(db_session, wid) == []
    assert svc.list_steps(db_session, wid) == []


def test_missing_workflow_raises(db_session: Session) -> None:
    with pytest.raises(AIWorkflowManagerError):
        _svc().get_workflow(db_session, 999999)
