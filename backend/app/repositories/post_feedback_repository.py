"""Репозиторий событий обратной связи по постам (post_feedback_events).

События — сигналы обучения (одобрение/правка/отклонение/аналитика). Секретов не
содержат (обеспечивает сервисный слой). Все выборки фильтруют по ``project_id``.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.post_feedback_event import PostFeedbackEvent


def create_event(db: Session, **fields: Any) -> PostFeedbackEvent:
    """Создать событие обратной связи."""
    event = PostFeedbackEvent(**fields)
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_by_id(db: Session, event_id: int) -> PostFeedbackEvent | None:
    """Событие по id (или None)."""
    return db.get(PostFeedbackEvent, event_id)


def list_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[PostFeedbackEvent]:
    """События проекта (свежие первыми), опционально по площадке."""
    stmt = select(PostFeedbackEvent).where(PostFeedbackEvent.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(PostFeedbackEvent.platform_key == platform_key)
    stmt = stmt.order_by(PostFeedbackEvent.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_for_post(db: Session, post_id: int, limit: int = 200) -> list[PostFeedbackEvent]:
    """События конкретного поста (свежие первыми)."""
    stmt = (
        select(PostFeedbackEvent)
        .where(PostFeedbackEvent.post_id == post_id)
        .order_by(PostFeedbackEvent.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def aggregate_by_project(db: Session, project_id: int) -> dict[str, int]:
    """Счётчики событий по типу для проекта: {event_type: count}."""
    stmt = (
        select(PostFeedbackEvent.event_type, func.count(PostFeedbackEvent.id))
        .where(PostFeedbackEvent.project_id == project_id)
        .group_by(PostFeedbackEvent.event_type)
    )
    return {event_type: int(count) for event_type, count in db.execute(stmt).all()}


def aggregate_by_platform(db: Session, project_id: int, platform_key: str) -> dict[str, int]:
    """Счётчики событий по типу для (project × platform)."""
    stmt = (
        select(PostFeedbackEvent.event_type, func.count(PostFeedbackEvent.id))
        .where(
            PostFeedbackEvent.project_id == project_id,
            PostFeedbackEvent.platform_key == platform_key,
        )
        .group_by(PostFeedbackEvent.event_type)
    )
    return {event_type: int(count) for event_type, count in db.execute(stmt).all()}


def count_for_project(
    db: Session, project_id: int, event_types: tuple[str, ...] | None = None
) -> int:
    """Число событий проекта (опционально по набору типов)."""
    stmt = select(func.count(PostFeedbackEvent.id)).where(
        PostFeedbackEvent.project_id == project_id
    )
    if event_types:
        stmt = stmt.where(PostFeedbackEvent.event_type.in_(event_types))
    return int(db.execute(stmt).scalar_one())
