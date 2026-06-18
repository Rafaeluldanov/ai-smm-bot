"""Тесты задачи планировщика для автономного прогона (без сети)."""

from sqlalchemy.orm import Session

from app.api.deps import get_autonomous_pipeline_service
from app.repositories.project_repository import create_project
from app.scheduler.jobs import autonomous_weekly_run_job
from app.schemas.project import ProjectCreate


def test_weekly_run_job(db_session: Session) -> None:
    create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    service = get_autonomous_pipeline_service()

    result = autonomous_weekly_run_job(db_session, service, "teeon")
    assert result.run.id
    assert result.run.mode == "semi_auto"
    assert result.run.status.startswith("completed")
