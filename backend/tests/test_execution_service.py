"""Тесты AIExecutionCoordinatorService — генерация/прогресс/координация (v0.7.8, offline).

Инварианты:
- generate строит цели (из quarter objectives) + задачи (3/цель) + прогресс;
- progress = completed/all × 100; complete/assign меняют только статус; регенерация не размножает;
- аудит execution.*; health возвращает прогресс+блокеры+рекомендации.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_execution_coordinator_service import AIExecutionCoordinatorService

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


def _execution(db: Session, pid: int, uid: int | None = None) -> int:
    pl = AIBusinessPlannerService(settings=_SETTINGS)
    gid = pl.create_business_goal(
        db, pid, goal_type="revenue", title="x5", target_value=5000000, current_value=1000000
    )["id"]
    sp = pl.generate_strategic_plan(db, gid)["plan"]["id"]
    pl.approve_plan(db, sp)
    return _svc().create_execution_plan(db, pid, strategic_plan_id=sp, user_id=uid)["id"]


def test_generate_objectives_and_tasks(db_session: Session) -> None:
    pid, uid = _project(db_session, "exsvc1")
    svc = _svc()
    ep = _execution(db_session, pid, uid)
    out = svc.generate_execution(db_session, ep, user_id=uid)
    assert out["plan"]["status"] == "active"
    assert len(out["objectives"]) == 4  # из 4 quarter objectives
    assert all(len(o["tasks"]) == 3 for o in out["objectives"])  # 3 задачи на цель
    assert out["plan"]["progress_percent"] == 0.0  # ничего не завершено


def test_progress_completed_over_all(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsvc2")
    svc = _svc()
    ep = _execution(db_session, pid)
    out = svc.generate_execution(db_session, ep)
    tasks = [t for o in out["objectives"] for t in o["tasks"]]
    assert len(tasks) == 12
    svc.complete_task(db_session, tasks[0]["id"])
    progress = svc.calculate_execution_progress(db_session, ep)
    assert progress == round(1 / 12 * 100, 1)


def test_progress_excludes_cancelled_tasks(db_session: Session) -> None:
    """Отменённые задачи исключаются из знаменателя прогресса (completed / non-cancelled)."""
    pid, _ = _project(db_session, "exsvc2b")
    svc = _svc()
    ep = _execution(db_session, pid)
    out = svc.generate_execution(db_session, ep)
    tasks = [t for o in out["objectives"] for t in o["tasks"]]
    assert len(tasks) == 12
    svc.complete_task(db_session, tasks[0]["id"])
    svc.set_task_status(db_session, tasks[1]["id"], "cancelled")
    # 1 completed из 11 не-отменённых → 9.1%
    assert svc.calculate_execution_progress(db_session, ep) == round(1 / 11 * 100, 1)


def test_progress_zero_when_all_cancelled(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsvc2c")
    svc = _svc()
    ep = _execution(db_session, pid)
    out = svc.generate_execution(db_session, ep)
    for o in out["objectives"]:
        for t in o["tasks"]:
            svc.set_task_status(db_session, t["id"], "cancelled")
    assert svc.calculate_execution_progress(db_session, ep) == 0.0


def test_complete_task_sets_status_and_progress(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsvc3")
    svc = _svc()
    ep = _execution(db_session, pid)
    out = svc.generate_execution(db_session, ep)
    task = out["objectives"][0]["tasks"][0]
    done = svc.complete_task(db_session, task["id"])
    assert done["status"] == "completed" and done["progress_percent"] == 100.0


def test_regenerate_does_not_multiply(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsvc4")
    svc = _svc()
    ep = _execution(db_session, pid)
    svc.generate_execution(db_session, ep)
    out = svc.generate_execution(db_session, ep)  # повторно
    assert len(out["objectives"]) == 4
    assert all(len(o["tasks"]) == 3 for o in out["objectives"])


def test_health_shape(db_session: Session) -> None:
    pid, _ = _project(db_session, "exsvc5")
    svc = _svc()
    ep = _execution(db_session, pid)
    svc.generate_execution(db_session, ep)
    health = svc.get_health(db_session, ep)
    for key in ("progress_percent", "tasks_total", "blockers", "recommendations"):
        assert key in health
    assert health["tasks_total"] == 12


def test_audit_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "exsvc6")
    svc = _svc()
    ep = _execution(db_session, pid, uid)
    out = svc.generate_execution(db_session, ep, user_id=uid)
    task = out["objectives"][0]["tasks"][0]
    svc.assign_owner(db_session, task["id"], uid, user_id=uid)
    svc.complete_task(db_session, task["id"], user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "execution.created",
        "execution.objective_created",
        "execution.task_created",
        "execution.task_assigned",
        "execution.task_completed",
    ):
        assert expected in actions
