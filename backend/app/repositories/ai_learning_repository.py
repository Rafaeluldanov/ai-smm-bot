"""Репозиторий AI Learning Loop (v0.6.5): профиль обучения + поток сигналов.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
События НЕ удаляются (reset профиля историю сигналов не трогает).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_learning_event import AILearningEvent
from app.models.ai_learning_profile import AILearningProfile

# Поля профиля, которые сервис может обновлять пересчётом (белый список).
_UPDATABLE_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "total_posts_analyzed",
        "total_feedback_events",
        "learning_score",
        "preferred_topics",
        "avoided_topics",
        "preferred_formats",
        "avoided_formats",
        "preferred_styles",
        "best_publish_times",
        "best_platforms",
        "content_rules",
        "media_preferences",
        "cta_preferences",
        "last_learning_at",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Profile                                                                      #
# ---------------------------------------------------------------------------- #


def get_profile(db: Session, project_id: int) -> AILearningProfile | None:
    """Профиль обучения проекта (или None)."""
    stmt = select(AILearningProfile).where(AILearningProfile.project_id == project_id)
    return db.execute(stmt).scalars().first()


def get_or_create_profile(
    db: Session, project_id: int, account_id: int | None = None
) -> AILearningProfile:
    """Получить или создать профиль (race-safe: при гонке ловим IntegrityError)."""
    existing = get_profile(db, project_id)
    if existing is not None:
        return existing
    profile = AILearningProfile(
        project_id=project_id,
        account_id=account_id,
        status="learning",
    )
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:  # параллельное создание — берём чужой профиль
        db.rollback()
        existing = get_profile(db, project_id)
        if existing is not None:
            return existing
        raise
    db.refresh(profile)
    return profile


def update_profile(db: Session, profile: AILearningProfile, **fields: Any) -> AILearningProfile:
    """Обновить поля профиля из пересчёта (только белый список полей)."""
    for key, value in fields.items():
        if key in _UPDATABLE_FIELDS:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------- #
# Events                                                                       #
# ---------------------------------------------------------------------------- #


def add_event(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    entity_type: str,
    entity_id: int | None,
    event_type: str,
    value: float = 0.0,
    source: str = "system",
    event_metadata: dict[str, Any] | None = None,
) -> AILearningEvent:
    """Записать одно событие/сигнал обучения (без секретов)."""
    event = AILearningEvent(
        project_id=project_id,
        account_id=account_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        value=float(value or 0.0),
        source=source,
        event_metadata=event_metadata or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_events(
    db: Session,
    project_id: int,
    *,
    entity_type: str | None = None,
    entity_id: int | None = None,
    event_type: str | None = None,
    source: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
) -> list[AILearningEvent]:
    """События проекта (свежие сверху), с опциональными фильтрами."""
    stmt = select(AILearningEvent).where(AILearningEvent.project_id == project_id)
    if entity_type is not None:
        stmt = stmt.where(AILearningEvent.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AILearningEvent.entity_id == entity_id)
    if event_type is not None:
        stmt = stmt.where(AILearningEvent.event_type == event_type)
    if source is not None:
        stmt = stmt.where(AILearningEvent.source == source)
    if since is not None:
        stmt = stmt.where(AILearningEvent.created_at >= since)
    stmt = stmt.order_by(AILearningEvent.id.desc()).limit(max(1, min(limit, 5000)))
    return list(db.execute(stmt).scalars().all())


def get_latest_event(
    db: Session,
    project_id: int,
    *,
    entity_type: str,
    entity_id: int | None,
    event_type: str,
) -> AILearningEvent | None:
    """Последнее событие данного типа для сущности (для идемпотентного анализа)."""
    stmt = (
        select(AILearningEvent)
        .where(
            AILearningEvent.project_id == project_id,
            AILearningEvent.entity_type == entity_type,
            AILearningEvent.entity_id == entity_id,
            AILearningEvent.event_type == event_type,
        )
        .order_by(AILearningEvent.id.desc())
    )
    return db.execute(stmt).scalars().first()


def count_events(db: Session, project_id: int, *, since: datetime | None = None) -> int:
    """Число событий проекта (опционально с даты)."""
    stmt = select(func.count(AILearningEvent.id)).where(AILearningEvent.project_id == project_id)
    if since is not None:
        stmt = stmt.where(AILearningEvent.created_at >= since)
    return int(db.execute(stmt).scalar_one())


def aggregate_event_counts(db: Session, project_id: int) -> dict[str, int]:
    """Счётчики событий по типам (event_type → count)."""
    stmt = (
        select(AILearningEvent.event_type, func.count(AILearningEvent.id))
        .where(AILearningEvent.project_id == project_id)
        .group_by(AILearningEvent.event_type)
    )
    return {row[0]: int(row[1]) for row in db.execute(stmt).all()}


# --- Удобные обёртки типизированных сигналов (Часть 5) ---


def add_topic_signal(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    topic_id: int | None,
    event_type: str,
    value: float = 0.0,
    source: str = "analytics",
    event_metadata: dict[str, Any] | None = None,
) -> AILearningEvent:
    """Сигнал по теме."""
    return add_event(
        db,
        project_id=project_id,
        account_id=account_id,
        entity_type="topic",
        entity_id=topic_id,
        event_type=event_type,
        value=value,
        source=source,
        event_metadata=event_metadata,
    )


def add_format_signal(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    event_type: str,
    value: float = 0.0,
    source: str = "analytics",
    event_metadata: dict[str, Any] | None = None,
) -> AILearningEvent:
    """Сигнал по формату (формат хранится в event_metadata['format'])."""
    return add_event(
        db,
        project_id=project_id,
        account_id=account_id,
        entity_type="format",
        entity_id=None,
        event_type=event_type,
        value=value,
        source=source,
        event_metadata=event_metadata,
    )


def add_media_signal(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    event_type: str,
    value: float = 0.0,
    source: str = "analytics",
    event_metadata: dict[str, Any] | None = None,
) -> AILearningEvent:
    """Сигнал по типу медиа (media_type хранится в event_metadata['media_type'])."""
    return add_event(
        db,
        project_id=project_id,
        account_id=account_id,
        entity_type="media",
        entity_id=None,
        event_type=event_type,
        value=value,
        source=source,
        event_metadata=event_metadata,
    )


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_profile_view(profile: AILearningProfile) -> dict[str, Any]:
    """Безопасное представление профиля (без секретов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "status": profile.status,
        "total_posts_analyzed": profile.total_posts_analyzed,
        "total_feedback_events": profile.total_feedback_events,
        "learning_score": round(float(profile.learning_score or 0.0), 1),
        "preferred_topics": list(profile.preferred_topics or []),
        "avoided_topics": list(profile.avoided_topics or []),
        "preferred_formats": list(profile.preferred_formats or []),
        "avoided_formats": list(profile.avoided_formats or []),
        "preferred_styles": list(profile.preferred_styles or []),
        "best_publish_times": list(profile.best_publish_times or []),
        "best_platforms": list(profile.best_platforms or []),
        "content_rules": dict(profile.content_rules or {}),
        "media_preferences": dict(profile.media_preferences or {}),
        "cta_preferences": dict(profile.cta_preferences or {}),
        "last_learning_at": (
            profile.last_learning_at.isoformat() if profile.last_learning_at else None
        ),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def public_event_view(event: AILearningEvent) -> dict[str, Any]:
    """Безопасное представление события."""
    return {
        "id": event.id,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "event_type": event.event_type,
        "value": round(float(event.value or 0.0), 4),
        "source": event.source,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def build_learning_summary(db: Session, profile: AILearningProfile) -> dict[str, Any]:
    """Сводка профиля + счётчики событий (для клиента/UI, без секретов)."""
    return {
        **public_profile_view(profile),
        "event_counts": aggregate_event_counts(db, profile.project_id),
        "recent_events": [
            public_event_view(e) for e in list_events(db, profile.project_id, limit=15)
        ],
    }
