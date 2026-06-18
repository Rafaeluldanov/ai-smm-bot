"""Репозиторий публикаций поста (PostPublication).

Бизнес-уникальность — пара (post_id, platform): upsert по ней обеспечивает
идемпотентность (один пост не публикуется в одну платформу дважды).
"""

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.post_publication import PostPublication
from app.schemas.post_publication import PostPublicationCreate, PostPublicationUpdate

# Статусы публикации, ожидающей отправки (для выборки «созревших»).
_DUE_STATUSES: tuple[str, ...] = ("scheduled", "pending")


def get_publication_by_id(db: Session, publication_id: int) -> PostPublication | None:
    """Вернуть публикацию по id или None."""
    return db.get(PostPublication, publication_id)


def get_publication_by_post_and_platform(
    db: Session, post_id: int, platform: str
) -> PostPublication | None:
    """Вернуть публикацию по (post_id, platform) или None."""
    stmt = select(PostPublication).where(
        PostPublication.post_id == post_id, PostPublication.platform == platform
    )
    return db.scalars(stmt).first()


def list_publications(
    db: Session,
    post_id: int | None = None,
    project_id: int | None = None,
    platform: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PostPublication]:
    """Вернуть список публикаций с фильтрами и пагинацией."""
    stmt = select(PostPublication).order_by(PostPublication.id)
    if post_id is not None:
        stmt = stmt.where(PostPublication.post_id == post_id)
    if project_id is not None:
        stmt = stmt.where(PostPublication.project_id == project_id)
    if platform is not None:
        stmt = stmt.where(PostPublication.platform == platform)
    if status is not None:
        stmt = stmt.where(PostPublication.status == status)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_publication(db: Session, data: PostPublicationCreate) -> PostPublication:
    """Создать публикацию."""
    publication = PostPublication(**data.model_dump())
    db.add(publication)
    db.commit()
    db.refresh(publication)
    return publication


def update_publication(
    db: Session, publication: PostPublication, data: PostPublicationUpdate
) -> PostPublication:
    """Частично обновить публикацию (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(publication, field, value)
    db.commit()
    db.refresh(publication)
    return publication


def upsert_publication_schedule(
    db: Session,
    post_id: int,
    project_id: int,
    platform: str,
    scheduled_at: datetime | None,
    target_id: str | None,
) -> PostPublication:
    """Создать или обновить запланированную публикацию по (post_id, platform).

    Идемпотентно: повторный вызов не плодит дубли. Уже опубликованную запись
    (status ``published``) не перезаписывает.
    """
    new_status = "scheduled" if scheduled_at is not None else "pending"
    existing = get_publication_by_post_and_platform(db, post_id, platform)

    if existing is None:
        publication = PostPublication(
            post_id=post_id,
            project_id=project_id,
            platform=platform,
            target_id=target_id,
            status=new_status,
            scheduled_at=scheduled_at,
        )
        db.add(publication)
        db.commit()
        db.refresh(publication)
        return publication

    if existing.status == "published":
        return existing

    existing.scheduled_at = scheduled_at
    existing.status = new_status
    if target_id is not None:
        existing.target_id = target_id
    db.commit()
    db.refresh(existing)
    return existing


def list_due_publications(db: Session, now: datetime) -> list[PostPublication]:
    """Вернуть «созревшие» публикации: scheduled/pending и время наступило.

    Учитываются записи без даты (``scheduled_at is null`` — публиковать сразу)
    и с датой ``scheduled_at <= now``.
    """
    stmt = (
        select(PostPublication)
        .where(
            PostPublication.status.in_(_DUE_STATUSES),
            or_(PostPublication.scheduled_at <= now, PostPublication.scheduled_at.is_(None)),
        )
        .order_by(PostPublication.scheduled_at, PostPublication.id)
    )
    return list(db.scalars(stmt).all())
