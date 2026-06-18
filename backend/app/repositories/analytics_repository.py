"""Репозиторий аналитических снимков (PostAnalyticsSnapshot).

Только доступ к данным: создание/чтение снимков. Расчёт метрик и агрегация —
в ``analytics_service``/``analytics_metrics``.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.schemas.analytics import PostAnalyticsSnapshotInsert, PostAnalyticsSnapshotUpdate


def get_snapshot_by_id(db: Session, snapshot_id: int) -> PostAnalyticsSnapshot | None:
    """Вернуть снимок по id или None."""
    return db.get(PostAnalyticsSnapshot, snapshot_id)


def list_snapshots(
    db: Session,
    post_id: int | None = None,
    project_id: int | None = None,
    topic_id: int | None = None,
    platform: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PostAnalyticsSnapshot]:
    """Вернуть снимки с фильтрами и пагинацией."""
    stmt = select(PostAnalyticsSnapshot).order_by(PostAnalyticsSnapshot.id)
    if post_id is not None:
        stmt = stmt.where(PostAnalyticsSnapshot.post_id == post_id)
    if project_id is not None:
        stmt = stmt.where(PostAnalyticsSnapshot.project_id == project_id)
    if topic_id is not None:
        stmt = stmt.where(PostAnalyticsSnapshot.topic_id == topic_id)
    if platform is not None:
        stmt = stmt.where(PostAnalyticsSnapshot.platform == platform)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_snapshot(db: Session, data: PostAnalyticsSnapshotInsert) -> PostAnalyticsSnapshot:
    """Создать снимок из полного набора колонок."""
    payload = data.model_dump()
    if payload.get("snapshot_at") is None:
        payload.pop("snapshot_at", None)
    snapshot = PostAnalyticsSnapshot(**payload)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def update_snapshot(
    db: Session, snapshot: PostAnalyticsSnapshot, data: PostAnalyticsSnapshotUpdate
) -> PostAnalyticsSnapshot:
    """Частично обновить снимок (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(snapshot, field, value)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_latest_snapshot_for_post_platform(
    db: Session, post_id: int, platform: str
) -> PostAnalyticsSnapshot | None:
    """Вернуть последний снимок поста на платформе или None."""
    stmt = (
        select(PostAnalyticsSnapshot)
        .where(
            PostAnalyticsSnapshot.post_id == post_id,
            PostAnalyticsSnapshot.platform == platform,
        )
        .order_by(PostAnalyticsSnapshot.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def list_snapshots_for_project(db: Session, project_id: int) -> list[PostAnalyticsSnapshot]:
    """Вернуть все снимки проекта (без пагинации)."""
    stmt = (
        select(PostAnalyticsSnapshot)
        .where(PostAnalyticsSnapshot.project_id == project_id)
        .order_by(PostAnalyticsSnapshot.id)
    )
    return list(db.scalars(stmt).all())


def list_snapshots_for_topic(db: Session, topic_id: int) -> list[PostAnalyticsSnapshot]:
    """Вернуть все снимки темы (без пагинации)."""
    stmt = (
        select(PostAnalyticsSnapshot)
        .where(PostAnalyticsSnapshot.topic_id == topic_id)
        .order_by(PostAnalyticsSnapshot.id)
    )
    return list(db.scalars(stmt).all())
