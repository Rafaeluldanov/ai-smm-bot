"""Тесты репозитория автономных прогонов."""

from sqlalchemy.orm import Session

from app.repositories import autonomous_run_repository as repo
from app.repositories.project_repository import create_project
from app.schemas.autonomous import (
    AutonomousRunCreate,
    AutonomousRunStepCreate,
    AutonomousRunStepUpdate,
    AutonomousRunUpdate,
)
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _run(db: Session, project_id: int, mode: str = "semi_auto", status: str = "created") -> int:
    return repo.create_run(
        db, AutonomousRunCreate(project_id=project_id, mode=mode, status=status)
    ).id


def test_create_and_update_run(db_session: Session) -> None:
    project_id = _project(db_session)
    run = repo.create_run(db_session, AutonomousRunCreate(project_id=project_id, mode="semi_auto"))
    assert repo.get_run_by_id(db_session, run.id) is not None
    updated = repo.update_run(db_session, run, AutonomousRunUpdate(status="completed"))
    assert updated.status == "completed"


def test_steps(db_session: Session) -> None:
    project_id = _project(db_session)
    run_id = _run(db_session, project_id)
    step = repo.create_step(
        db_session, AutonomousRunStepCreate(run_id=run_id, step_name="select_topics")
    )
    repo.update_step(db_session, step, AutonomousRunStepUpdate(status="completed"))
    steps = repo.list_steps(db_session, run_id)
    assert len(steps) == 1
    assert steps[0].status == "completed"


def test_list_runs_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    _run(db_session, project_id, mode="semi_auto", status="completed")
    _run(db_session, project_id, mode="dry_run", status="completed_with_warnings")
    assert len(repo.list_runs(db_session, project_id=project_id)) == 2
    assert len(repo.list_runs(db_session, mode="dry_run")) == 1
    assert len(repo.list_runs(db_session, status="completed")) == 1


def test_latest_run(db_session: Session) -> None:
    project_id = _project(db_session)
    _run(db_session, project_id)
    second = _run(db_session, project_id)
    latest = repo.get_latest_run_for_project(db_session, project_id)
    assert latest is not None
    assert latest.id == second
