"""Тесты планировщика публикаций (без сети)."""

from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.scheduler.jobs import publish_due_publications_job
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostScheduleRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry


def _service() -> PostPublicationService:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram"), "vk": FakePublishingClient("vk")}
    )
    return PostPublicationService(registry=registry, default_targets={"telegram": "@c", "vk": "-1"})


def test_publish_due_job_publishes(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    post_id = post_repository.create_post(
        db_session, PostCreate(project_id=project.id, title="Футболки", status="approved")
    ).id
    service = _service()
    service.schedule_post(db_session, post_id, PostScheduleRequest())

    result = publish_due_publications_job(db_session, service, now=None)
    assert result.processed_posts == 1
    assert result.published_count == 2


def test_publish_due_job_no_due(db_session: Session) -> None:
    result = publish_due_publications_job(db_session, _service(), now=None)
    assert result.processed_posts == 0
    assert result.published_count == 0
