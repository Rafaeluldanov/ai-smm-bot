"""Тесты репозитория проектов (прямой доступ к БД)."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import project_repository as repo
from app.repositories.project_repository import SlugAlreadyExistsError
from app.schemas.project import ProjectCreate, ProjectUpdate


def test_create_and_get_by_slug(db_session: Session) -> None:
    created = repo.create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    assert created.id is not None

    fetched = repo.get_project_by_slug(db_session, "teeon")
    assert fetched is not None
    assert fetched.id == created.id


def test_duplicate_slug_raises(db_session: Session) -> None:
    repo.create_project(db_session, ProjectCreate(name="A", slug="dup"))
    with pytest.raises(SlugAlreadyExistsError):
        repo.create_project(db_session, ProjectCreate(name="B", slug="dup"))


def test_deactivate_does_not_delete(db_session: Session) -> None:
    project = repo.create_project(db_session, ProjectCreate(name="X", slug="proj-x"))
    repo.deactivate_project(db_session, project)

    fetched = repo.get_project_by_id(db_session, project.id)
    assert fetched is not None  # запись на месте, не удалена
    assert fetched.is_active is False


def test_list_active_only(db_session: Session) -> None:
    active = repo.create_project(db_session, ProjectCreate(name="Active", slug="active"))
    inactive = repo.create_project(db_session, ProjectCreate(name="Inactive", slug="inactive"))
    repo.deactivate_project(db_session, inactive)

    active_ids = [p.id for p in repo.list_projects(db_session, active_only=True)]
    all_ids = [p.id for p in repo.list_projects(db_session, active_only=False)]

    assert active.id in active_ids
    assert inactive.id not in active_ids
    assert inactive.id in all_ids


def test_update_partial(db_session: Session) -> None:
    project = repo.create_project(db_session, ProjectCreate(name="Old", slug="proj"))
    updated = repo.update_project(db_session, project, ProjectUpdate(description="новое описание"))

    assert updated.description == "новое описание"
    assert updated.name == "Old"  # остальные поля не тронуты
    assert updated.slug == "proj"
