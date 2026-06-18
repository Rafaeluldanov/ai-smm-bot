"""Тесты репозитория тем."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import topic_repository as repo
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import InvalidTopicStatusError, TopicNotFoundError
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _candidate(title: str, cluster: str = "футболки", status: str = "recommended") -> dict:
    return {
        "title": title,
        "cluster": cluster,
        "priority_score": 75.0,
        "business_priority": 90,
        "seo_keywords": ["футболки с логотипом"],
        "status": status,
    }


def test_create_and_get_by_title(db_session: Session) -> None:
    project_id = _project(db_session)
    repo.create_topic(
        db_session,
        TopicCreate(project_id=project_id, title="Футболки на заказ", cluster="футболки"),
    )
    found = repo.get_topic_by_project_and_title(db_session, project_id, "Футболки на заказ")
    assert found is not None
    assert found.cluster == "футболки"


def test_upsert_no_duplicate(db_session: Session) -> None:
    project_id = _project(db_session)
    t1, a1 = repo.upsert_topic_candidate(db_session, project_id, _candidate("Тема А"))
    t2, a2 = repo.upsert_topic_candidate(db_session, project_id, _candidate("Тема А"))
    assert a1 == "created"
    assert a2 == "unchanged"
    assert t1.id == t2.id
    assert len(repo.list_topics(db_session, project_id=project_id)) == 1


def test_list_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    repo.upsert_topic_candidate(db_session, project_id, _candidate("A", cluster="футболки"))
    repo.upsert_topic_candidate(db_session, project_id, _candidate("B", cluster="худи"))
    assert len(repo.list_topics(db_session, project_id=project_id)) == 2
    assert len(repo.list_topics(db_session, project_id=project_id, cluster="худи")) == 1
    assert len(repo.list_topics(db_session, project_id=project_id, status="recommended")) == 2
    assert len(repo.list_topics(db_session, project_id=project_id, status="planned")) == 0


def test_mark_topic_status(db_session: Session) -> None:
    project_id = _project(db_session)
    topic, _ = repo.upsert_topic_candidate(db_session, project_id, _candidate("A"))
    updated = repo.mark_topic_status(db_session, topic.id, "planned")
    assert updated.status == "planned"


def test_mark_topic_status_invalid(db_session: Session) -> None:
    project_id = _project(db_session)
    topic, _ = repo.upsert_topic_candidate(db_session, project_id, _candidate("A"))
    with pytest.raises(InvalidTopicStatusError):
        repo.mark_topic_status(db_session, topic.id, "bogus")


def test_mark_topic_status_missing(db_session: Session) -> None:
    with pytest.raises(TopicNotFoundError):
        repo.mark_topic_status(db_session, 99999, "planned")
