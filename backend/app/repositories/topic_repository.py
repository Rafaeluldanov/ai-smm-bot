"""Репозиторий для работы с темами (Topic).

Бизнес-уникальность темы — пара (project_id, title). Метод upsert использует
это, чтобы повторный выбор тем не плодил дубликаты.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.topic import Topic
from app.schemas.topic import TopicCreate, TopicUpdate

# Допустимые статусы темы.
ALLOWED_TOPIC_STATUSES: list[str] = ["candidate", "recommended", "planned", "archived"]


class TopicNotFoundError(Exception):
    """Тема не найдена в базе данных."""

    def __init__(self, topic_id: int) -> None:
        self.topic_id = topic_id
        super().__init__(f"Тема id={topic_id} не найдена")


class InvalidTopicStatusError(Exception):
    """Передан неизвестный статус темы."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"Неизвестный статус темы: '{status}'")


def get_topic_by_id(db: Session, topic_id: int) -> Topic | None:
    """Вернуть тему по id или None."""
    return db.get(Topic, topic_id)


def get_topic_by_project_and_title(db: Session, project_id: int, title: str) -> Topic | None:
    """Вернуть тему по (project_id, title) или None."""
    stmt = select(Topic).where(Topic.project_id == project_id, Topic.title == title)
    return db.scalars(stmt).first()


def list_topics(
    db: Session,
    project_id: int | None = None,
    status: str | None = None,
    cluster: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Topic]:
    """Вернуть список тем с фильтрами и пагинацией."""
    stmt = select(Topic).order_by(Topic.priority_score.desc(), Topic.id)
    if project_id is not None:
        stmt = stmt.where(Topic.project_id == project_id)
    if status is not None:
        stmt = stmt.where(Topic.status == status)
    if cluster is not None:
        stmt = stmt.where(Topic.cluster == cluster)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_topic(db: Session, data: TopicCreate) -> Topic:
    """Создать тему."""
    topic = Topic(**data.model_dump())
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return topic


def update_topic(db: Session, topic: Topic, data: TopicUpdate) -> Topic:
    """Частично обновить тему."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(topic, field, value)
    db.commit()
    db.refresh(topic)
    return topic


def upsert_topic_candidate(
    db: Session, project_id: int, candidate: dict[str, Any]
) -> tuple[Topic, str]:
    """Создать или обновить тему по (project_id, title).

    Возвращает (topic, action), где action ∈ {"created", "updated", "unchanged"}.
    """
    title = str(candidate["title"])
    cluster = candidate.get("cluster")
    priority_score = float(candidate.get("priority_score", 0.0))
    business_priority = int(candidate.get("business_priority", 0))
    seo_keywords = list(candidate.get("seo_keywords", []))
    status = str(candidate.get("status", "candidate"))

    existing = get_topic_by_project_and_title(db, project_id, title)
    if existing is None:
        topic = Topic(
            project_id=project_id,
            title=title,
            cluster=cluster,
            priority_score=priority_score,
            business_priority=business_priority,
            seo_keywords=seo_keywords,
            status=status,
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)
        return topic, "created"

    changed = False
    for field, value in (
        ("cluster", cluster),
        ("priority_score", priority_score),
        ("business_priority", business_priority),
        ("seo_keywords", seo_keywords),
        ("status", status),
    ):
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed = True

    if not changed:
        return existing, "unchanged"

    db.commit()
    db.refresh(existing)
    return existing, "updated"


def mark_topic_status(db: Session, topic_id: int, status: str) -> Topic:
    """Сменить статус темы. 422 (InvalidTopicStatusError) / 404 (TopicNotFoundError)."""
    if status not in ALLOWED_TOPIC_STATUSES:
        raise InvalidTopicStatusError(status)
    topic = get_topic_by_id(db, topic_id)
    if topic is None:
        raise TopicNotFoundError(topic_id)
    topic.status = status
    db.commit()
    db.refresh(topic)
    return topic
