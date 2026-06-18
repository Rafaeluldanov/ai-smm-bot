"""Тесты репозитория постов."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import post_repository as repo
from app.repositories.post_repository import PostNotFoundError
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.post import PostCreate, PostUpdate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int) -> int:
    return create_topic(
        db, TopicCreate(project_id=project_id, title="Футболки", cluster="футболки")
    ).id


def _post(db: Session, project_id: int, topic_id: int, status: str = "draft") -> int:
    return repo.create_post(
        db,
        PostCreate(
            project_id=project_id,
            topic_id=topic_id,
            title="Футболки с логотипом",
            telegram_text="t",
            vk_text="v",
            instagram_text="i",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    ).id


def test_create_and_get(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)
    found = repo.get_post_by_id(db_session, post_id)
    assert found is not None
    assert found.title == "Футболки с логотипом"
    assert found.status == "draft"


def test_list_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    _post(db_session, project_id, topic_id, status="draft")
    _post(db_session, project_id, topic_id, status="needs_media")
    assert len(repo.list_posts(db_session, project_id=project_id)) == 2
    assert len(repo.list_posts(db_session, topic_id=topic_id)) == 2
    assert len(repo.list_posts(db_session, status="draft")) == 1
    assert len(repo.list_posts(db_session, status="published")) == 0


def test_update_post(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)
    post = repo.get_post_by_id(db_session, post_id)
    assert post is not None
    updated = repo.update_post(db_session, post, PostUpdate(title="Новый заголовок"))
    assert updated.title == "Новый заголовок"


def test_update_status_and_missing(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    post_id = _post(db_session, project_id, topic_id)
    updated = repo.update_post_status(db_session, post_id, "needs_review")
    assert updated.status == "needs_review"
    with pytest.raises(PostNotFoundError):
        repo.update_post_status(db_session, 99999, "draft")


def test_existing_post_for_topic(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id)
    assert repo.get_existing_post_for_topic(db_session, topic_id) is None
    post_id = _post(db_session, project_id, topic_id, status="draft")
    existing = repo.get_existing_post_for_topic(db_session, topic_id)
    assert existing is not None
    assert existing.id == post_id
