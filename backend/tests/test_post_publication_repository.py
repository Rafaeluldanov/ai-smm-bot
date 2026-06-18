"""Тесты репозитория публикаций поста."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories import post_publication_repository as repo
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post(db: Session, project_id: int, status: str = "approved") -> int:
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Футболки", status=status)
    ).id


def _pub(
    project_id: int,
    post_id: int,
    platform: str,
    status: str = "pending",
    scheduled_at: datetime | None = None,
) -> PostPublicationCreate:
    return PostPublicationCreate(
        post_id=post_id,
        project_id=project_id,
        platform=platform,
        status=status,
        scheduled_at=scheduled_at,
    )


def test_create_and_get(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    created = repo.create_publication(db_session, _pub(project_id, post_id, "telegram"))
    assert repo.get_publication_by_id(db_session, created.id) is not None
    found = repo.get_publication_by_post_and_platform(db_session, post_id, "telegram")
    assert found is not None
    assert found.id == created.id


def test_upsert_no_duplicate(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    p1 = repo.upsert_publication_schedule(db_session, post_id, project_id, "telegram", None, "@c")
    p2 = repo.upsert_publication_schedule(db_session, post_id, project_id, "telegram", None, "@c")
    assert p1.id == p2.id
    assert len(repo.list_publications(db_session, post_id=post_id)) == 1


def test_list_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    repo.create_publication(db_session, _pub(project_id, post_id, "telegram"))
    repo.create_publication(db_session, _pub(project_id, post_id, "vk", status="published"))
    assert len(repo.list_publications(db_session, post_id=post_id)) == 2
    assert len(repo.list_publications(db_session, platform="vk")) == 1
    assert len(repo.list_publications(db_session, status="published")) == 1
    assert len(repo.list_publications(db_session, status="failed")) == 0


def test_list_due(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    post2 = _post(db_session, project_id)
    # Прошедшая дата — созрела.
    repo.create_publication(
        db_session,
        _pub(
            project_id, post_id, "telegram", status="scheduled", scheduled_at=datetime(2026, 6, 1)
        ),
    )
    # Без даты (pending) — публиковать сразу.
    repo.create_publication(db_session, _pub(project_id, post_id, "vk", status="pending"))
    # Будущая дата — ещё не созрела.
    repo.create_publication(
        db_session,
        _pub(project_id, post2, "telegram", status="scheduled", scheduled_at=datetime(2026, 7, 1)),
    )

    due = repo.list_due_publications(db_session, datetime(2026, 6, 18))
    keys = {(p.post_id, p.platform) for p in due}
    assert (post_id, "telegram") in keys
    assert (post_id, "vk") in keys
    assert (post2, "telegram") not in keys
