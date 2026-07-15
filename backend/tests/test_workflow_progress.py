"""Тесты расчёта прогресса и health процесса (v0.7.2).

progress = completed / (все, кроме cancelled) × 100 → 0..100; health зависит от блокеров/просрочек.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import workflow_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_workflow_manager_service import AIWorkflowManagerService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIWorkflowManagerService:
    return AIWorkflowManagerService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _wf(db: Session, pid: int) -> int:
    return _svc().create_workflow_from_goal(
        db, pid, name="P", workflow_type="custom", status="active"
    )["id"]


def test_progress_zero_when_no_steps(db_session: Session) -> None:
    pid = _project(db_session, "wfp1")
    assert _svc().calculate_workflow_progress(db_session, _wf(db_session, pid)) == 0.0


def test_progress_fraction_completed(db_session: Session) -> None:
    pid = _project(db_session, "wfp2")
    svc = _svc()
    wid = _wf(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)  # 3 default custom steps
    assert len(steps) == 3
    svc.complete_step(db_session, steps[0]["id"])
    assert svc.calculate_workflow_progress(db_session, wid) == round(100 / 3, 1)
    svc.complete_step(db_session, steps[1]["id"])
    svc.complete_step(db_session, steps[2]["id"])
    assert svc.calculate_workflow_progress(db_session, wid) == 100.0


def test_cancelled_steps_excluded_from_denominator(db_session: Session) -> None:
    pid = _project(db_session, "wfp3")
    svc = _svc()
    wid = _wf(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)  # 3
    svc.update_step_status(db_session, steps[2]["id"], "cancelled")
    svc.complete_step(db_session, steps[0]["id"])
    # 1 completed из 2 незакрытых (3-й cancelled исключён) → 50%
    assert svc.calculate_workflow_progress(db_session, wid) == 50.0


def test_health_penalises_blockers_and_overdue(db_session: Session) -> None:
    pid = _project(db_session, "wfp4")
    svc = _svc()
    wid = _wf(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)
    # просроченный этап
    step = repo.get_step(db_session, steps[0]["id"])
    step.deadline = datetime.now(UTC) - timedelta(days=2)
    db_session.commit()
    svc.create_blocker(db_session, wid, blocker_type="external", title="Внешнее ожидание")
    health = svc.analyze_workflow_health(db_session, wid)
    assert health["overdue_steps"] == 1
    assert health["open_blockers"] == 1
    assert health["health_score"] < 100
    assert any("роч" in r.lower() or "блокер" in r.lower() for r in health["risks"])


def test_health_counts_stuck_steps(db_session: Session) -> None:
    """Этап in_progress без изменений ≥7 дней считается застрявшим (health penalty + risk)."""
    pid = _project(db_session, "wfp5")
    svc = _svc()
    wid = _wf(db_session, pid)
    steps = svc.generate_workflow_steps(db_session, wid)
    svc.update_step_status(db_session, steps[0]["id"], "in_progress")
    step = repo.get_step(db_session, steps[0]["id"])
    step.updated_at = datetime.now(UTC) - timedelta(days=8)
    db_session.commit()
    health = svc.analyze_workflow_health(db_session, wid)
    assert health["stuck_steps"] == 1
    assert health["health_score"] < 100
    assert any("движени" in r.lower() for r in health["risks"])
