"""Тесты задачи планировщика по сбору аналитики (без сети)."""

from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.scheduler.jobs import collect_publication_analytics_job
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsService


def _published_publication(db: Session) -> int:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    post = post_repository.create_post(
        db, PostCreate(project_id=project.id, title="Пост", status="published")
    )
    return post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post.id, project_id=project.id, platform="telegram", status="published"
        ),
    ).id


def test_collect_job_creates_snapshots(db_session: Session) -> None:
    publication_id = _published_publication(db_session)
    service = AnalyticsService(provider=FakeAnalyticsProvider())

    snapshots = collect_publication_analytics_job(db_session, service, [publication_id])
    assert len(snapshots) == 1
    assert snapshots[0].source == "fake_provider"


def test_collect_job_defaults_to_published(db_session: Session) -> None:
    _published_publication(db_session)
    service = AnalyticsService(provider=FakeAnalyticsProvider())

    snapshots = collect_publication_analytics_job(db_session, service)
    assert len(snapshots) == 1
