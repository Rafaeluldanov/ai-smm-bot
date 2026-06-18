"""Тесты сервиса обратной связи аналитики для выбора тем."""

from sqlalchemy.orm import Session

from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.repositories.topic_repository import create_topic
from app.schemas.analytics import PostAnalyticsSnapshotCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.schemas.topic import TopicCreate
from app.services.analytics_provider import FakeAnalyticsProvider
from app.services.analytics_service import AnalyticsService
from app.services.topic_analytics_feedback_service import TopicAnalyticsFeedbackService


def _feedback() -> tuple[AnalyticsService, TopicAnalyticsFeedbackService]:
    analytics = AnalyticsService(provider=FakeAnalyticsProvider())
    return analytics, TopicAnalyticsFeedbackService(analytics)


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _topic(db: Session, project_id: int, cluster: str) -> int:
    return create_topic(
        db, TopicCreate(project_id=project_id, title=f"Тема {cluster}", cluster=cluster)
    ).id


def _post(db: Session, project_id: int, topic_id: int) -> int:
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, topic_id=topic_id, title="Пост", status="published")
    ).id


def test_adjustments_boost_and_penalty(db_session: Session) -> None:
    project_id = _project(db_session)
    high = _topic(db_session, project_id, "футболки")
    low = _topic(db_session, project_id, "худи")
    analytics, feedback = _feedback()
    analytics.ingest_snapshot(
        db_session,
        PostAnalyticsSnapshotCreate(
            post_id=_post(db_session, project_id, high),
            platform="telegram",
            impressions=5000,
            reach=5000,
            likes=1000,
            clicks=600,
        ),
    )
    analytics.ingest_snapshot(
        db_session,
        PostAnalyticsSnapshotCreate(
            post_id=_post(db_session, project_id, low),
            platform="telegram",
            impressions=100,
            reach=100,
            likes=0,
            clicks=0,
        ),
    )

    adjustments = feedback.build_business_priority_adjustments(db_session, project_id)
    assert adjustments["футболки"] == 10
    assert adjustments["худи"] == -10


def test_notes_when_no_snapshots(db_session: Session) -> None:
    project_id = _project(db_session)
    _, feedback = _feedback()
    notes = feedback.build_feedback_notes(db_session, project_id)
    assert notes  # есть предупреждения об отсутствии данных
