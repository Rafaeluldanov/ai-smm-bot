"""Тесты сервиса планирования и публикации постов."""

from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from app.integrations.publishing import FakePublishingClient
from app.repositories import post_publication_repository as pub_repo
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest, PostScheduleRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import (
    PostNotPublishableError,
    PostPublicationService,
)
from app.services.publication_platform_registry import PublicationPlatformRegistry


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post(db: Session, project_id: int, status: str = "approved") -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=None,
            title="Футболки",
            telegram_text="tg",
            vk_text="vk",
            instagram_text="ig",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    ).id


def _service(success: bool = True) -> PostPublicationService:
    registry = PublicationPlatformRegistry(
        {
            "telegram": FakePublishingClient("telegram", fail=not success),
            "vk": FakePublishingClient("vk", fail=not success),
        }
    )
    return PostPublicationService(
        registry=registry, default_targets={"telegram": "@chan", "vk": "-100"}
    )


def test_schedule_sets_scheduled(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    result = _service().schedule_post(db_session, post_id, PostScheduleRequest())
    assert result.post_status == "scheduled"
    assert {p.platform for p in result.publications} == {"telegram", "vk"}


def test_schedule_idempotent(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service()
    service.schedule_post(db_session, post_id, PostScheduleRequest(platforms=["telegram"]))
    service.schedule_post(db_session, post_id, PostScheduleRequest(platforms=["telegram"]))
    assert len(pub_repo.list_publications(db_session, post_id=post_id, platform="telegram")) == 1


def test_publish_success(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service(success=True)
    service.schedule_post(db_session, post_id, PostScheduleRequest())

    result = service.publish_post(db_session, post_id, PostPublishRequest())
    assert result.published_count == 2
    assert result.post_status == "published"
    pub = pub_repo.get_publication_by_post_and_platform(db_session, post_id, "telegram")
    assert pub is not None
    assert pub.status == "published"
    assert pub.external_post_id


def test_publish_failure(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service(success=False)
    service.schedule_post(db_session, post_id, PostScheduleRequest())

    result = service.publish_post(db_session, post_id, PostPublishRequest())
    assert result.failed_count == 2
    assert result.post_status != "published"
    pub = pub_repo.get_publication_by_post_and_platform(db_session, post_id, "telegram")
    assert pub is not None
    assert pub.status == "failed"
    assert pub.error_message


def test_already_published_skipped(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service(success=True)
    service.schedule_post(db_session, post_id, PostScheduleRequest())
    service.publish_post(db_session, post_id, PostPublishRequest())

    again = service.publish_post(db_session, post_id, PostPublishRequest())
    assert again.skipped_count == 2
    assert again.published_count == 0


def test_force_republishes(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service(success=True)
    service.schedule_post(db_session, post_id, PostScheduleRequest())
    service.publish_post(db_session, post_id, PostPublishRequest())

    forced = service.publish_post(db_session, post_id, PostPublishRequest(force=True))
    assert forced.published_count == 2
    pub = pub_repo.get_publication_by_post_and_platform(db_session, post_id, "telegram")
    assert pub is not None
    assert pub.attempts >= 2


def test_publish_due(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "approved")
    service = _service(success=True)
    service.schedule_post(
        db_session, post_id, PostScheduleRequest(scheduled_at=datetime(2026, 6, 1))
    )

    result = service.publish_due_publications(db_session, now=datetime(2026, 6, 18))
    assert result.processed_posts == 1
    assert result.published_count == 2


def test_draft_not_publishable(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, "draft")
    with pytest.raises(PostNotPublishableError):
        _service().schedule_post(db_session, post_id, PostScheduleRequest())
