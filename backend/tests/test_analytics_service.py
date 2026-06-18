"""Тесты сервиса аналитики."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.analytics import PostAnalyticsSnapshotCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsInputError, AnalyticsService


def _service() -> AnalyticsService:
    return AnalyticsService(provider=FakeAnalyticsProvider())


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int, cluster: str) -> int:
    return create_topic(
        db, TopicCreate(project_id=project_id, title=f"Тема {cluster}", cluster=cluster)
    ).id


def _post(db: Session, project_id: int, topic_id: int | None = None) -> int:
    return post_repository.create_post(
        db,
        PostCreate(project_id=project_id, topic_id=topic_id, title="Пост", status="published"),
    ).id


def _publication(db: Session, project_id: int, post_id: int) -> int:
    return post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post_id, project_id=project_id, platform="telegram", status="published"
        ),
    ).id


def _high(post_id: int) -> PostAnalyticsSnapshotCreate:
    return PostAnalyticsSnapshotCreate(
        post_id=post_id, platform="telegram", impressions=5000, reach=5000, likes=1000, clicks=600
    )


def _low(post_id: int) -> PostAnalyticsSnapshotCreate:
    return PostAnalyticsSnapshotCreate(
        post_id=post_id, platform="telegram", impressions=100, reach=100, likes=0, clicks=0
    )


def test_ingest_calculates_rates(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    snapshot = _service().ingest_snapshot(
        db_session,
        PostAnalyticsSnapshotCreate(
            post_id=post_id, platform="telegram", impressions=1000, likes=80, clicks=20
        ),
    )
    assert snapshot.ctr == 0.02
    assert snapshot.engagement_rate == 0.08
    assert snapshot.project_id == project_id


def test_ingest_for_publication(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    publication_id = _publication(db_session, project_id, post_id)
    snapshot = _service().ingest_for_publication(
        db_session, publication_id, metrics={"impressions": 1000, "clicks": 50}
    )
    assert snapshot.post_publication_id == publication_id
    assert snapshot.platform == "telegram"


def test_ingest_for_publication_requires_metrics(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    publication_id = _publication(db_session, project_id, post_id)
    with pytest.raises(AnalyticsInputError):
        _service().ingest_for_publication(db_session, publication_id, metrics=None)


def test_fetch_uses_fake_provider(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    publication_id = _publication(db_session, project_id, post_id)
    snapshot = _service().fetch_and_store_for_publication(db_session, publication_id)
    assert snapshot.source == "fake_provider"
    assert snapshot.impressions > 0


def test_post_performance_aggregates(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id)
    service = _service()
    service.ingest_snapshot(
        db_session,
        PostAnalyticsSnapshotCreate(
            post_id=post_id, platform="telegram", impressions=1000, clicks=10
        ),
    )
    service.ingest_snapshot(
        db_session,
        PostAnalyticsSnapshotCreate(post_id=post_id, platform="vk", impressions=2000, clicks=40),
    )
    report = service.get_post_performance(db_session, post_id)
    assert report.snapshots_count == 2
    assert report.total_impressions == 3000
    assert set(report.platforms) == {"telegram", "vk"}


def test_topic_and_cluster_performance(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id, "футболки")
    post_id = _post(db_session, project_id, topic_id)
    service = _service()
    service.ingest_snapshot(db_session, _high(post_id))

    topics = service.get_topic_performance(db_session, project_id)
    assert len(topics.items) == 1
    assert topics.items[0].topic_id == topic_id
    assert topics.items[0].performance_score > 0

    clusters = service.get_cluster_performance(db_session, project_id)
    assert clusters.items[0].cluster == "футболки"


def test_project_summary(db_session: Session) -> None:
    project_id = _project(db_session)
    topic_id = _topic(db_session, project_id, "футболки")
    post_id = _post(db_session, project_id, topic_id)
    service = _service()
    service.ingest_snapshot(db_session, _high(post_id))

    summary = service.get_project_summary(db_session, project_id)
    assert summary.snapshots_count == 1
    assert summary.published_posts_count == 1
    assert summary.total_impressions == 5000
    assert summary.top_topics
    assert summary.top_clusters


def test_feedback_signals(db_session: Session) -> None:
    project_id = _project(db_session)
    high_topic = _topic(db_session, project_id, "футболки")
    low_topic = _topic(db_session, project_id, "худи")
    service = _service()
    service.ingest_snapshot(db_session, _high(_post(db_session, project_id, high_topic)))
    service.ingest_snapshot(db_session, _low(_post(db_session, project_id, low_topic)))

    report = service.build_feedback_signals(db_session, project_id)
    signal_types = {s.signal_type for s in report.signals}
    assert "boost_cluster" in signal_types
    assert "review_content_format" in signal_types
