"""Тесты репозитория аналитических снимков."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.repositories import analytics_repository as repo
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.analytics import PostAnalyticsSnapshotInsert
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post(db: Session, project_id: int) -> int:
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Футболки", status="published")
    ).id


def _insert(
    project_id: int, post_id: int, platform: str = "telegram", impressions: int = 1000
) -> PostAnalyticsSnapshotInsert:
    return PostAnalyticsSnapshotInsert(
        post_id=post_id,
        project_id=project_id,
        platform=platform,
        snapshot_at=datetime(2026, 6, 18, 12, 0, 0),
        impressions=impressions,
        clicks=20,
        ctr=0.02,
        engagement_rate=0.05,
    )


def test_create_and_get(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    created = repo.create_snapshot(db_session, _insert(project_id, post_id))
    assert repo.get_snapshot_by_id(db_session, created.id) is not None
    assert created.ctr == 0.02


def test_list_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    repo.create_snapshot(db_session, _insert(project_id, post_id, platform="telegram"))
    repo.create_snapshot(db_session, _insert(project_id, post_id, platform="vk"))
    assert len(repo.list_snapshots(db_session, post_id=post_id)) == 2
    assert len(repo.list_snapshots(db_session, platform="vk")) == 1
    assert len(repo.list_snapshots(db_session, project_id=project_id)) == 2
    assert len(repo.list_snapshots_for_project(db_session, project_id)) == 2


def test_latest_snapshot(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    repo.create_snapshot(db_session, _insert(project_id, post_id, impressions=1000))
    second = repo.create_snapshot(db_session, _insert(project_id, post_id, impressions=2000))
    latest = repo.get_latest_snapshot_for_post_platform(db_session, post_id, "telegram")
    assert latest is not None
    assert latest.id == second.id
