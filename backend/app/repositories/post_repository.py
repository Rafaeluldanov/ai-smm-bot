"""Репозиторий для работы с постами (Post).

Изолирует доступ к БД для сущности Post. Проверка допустимости переходов
статусов живёт в ``post_status_service`` и вызывается на уровне API/сервиса —
здесь только сохранение данных.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.post import Post
from app.schemas.post import PostCreate, PostUpdate

# Статусы черновика, по которым ищем уже существующий пост темы (anti-duplicate).
_DRAFT_STATUSES: tuple[str, ...] = ("draft", "needs_media", "needs_review")


class PostNotFoundError(Exception):
    """Пост не найден в базе данных."""

    def __init__(self, post_id: int) -> None:
        self.post_id = post_id
        super().__init__(f"Пост id={post_id} не найден")


def get_post_by_id(db: Session, post_id: int) -> Post | None:
    """Вернуть пост по id или None."""
    return db.get(Post, post_id)


def list_posts(
    db: Session,
    project_id: int | None = None,
    topic_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Post]:
    """Вернуть список постов с фильтрами и пагинацией."""
    stmt = select(Post).order_by(Post.id)
    if project_id is not None:
        stmt = stmt.where(Post.project_id == project_id)
    if topic_id is not None:
        stmt = stmt.where(Post.topic_id == topic_id)
    if status is not None:
        stmt = stmt.where(Post.status == status)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_recent_posts(db: Session, project_id: int, limit: int = 50) -> list[Post]:
    """Вернуть последние посты проекта (по убыванию id — свежие первыми)."""
    stmt = select(Post).where(Post.project_id == project_id).order_by(Post.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def create_post(db: Session, data: PostCreate) -> Post:
    """Создать пост."""
    post = Post(**data.model_dump())
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def update_post(db: Session, post: Post, data: PostUpdate) -> Post:
    """Частично обновить пост (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(post, field, value)
    db.commit()
    db.refresh(post)
    return post


def update_post_status(db: Session, post_id: int, status: str) -> Post:
    """Сменить статус поста. Бросает PostNotFoundError, если поста нет.

    Допустимость перехода проверяется вызывающим кодом через
    ``post_status_service.validate_transition``.
    """
    post = get_post_by_id(db, post_id)
    if post is None:
        raise PostNotFoundError(post_id)
    post.status = status
    db.commit()
    db.refresh(post)
    return post


def get_existing_post_for_topic(
    db: Session, topic_id: int, platform_group: str | None = None
) -> Post | None:
    """Вернуть последний незакрытый пост темы (draft/needs_media/needs_review).

    Помогает не плодить дубли при повторной генерации. ``platform_group``
    зарезервирован на будущее (в модели поста разбиения по платформам нет).
    """
    stmt = (
        select(Post)
        .where(Post.topic_id == topic_id, Post.status.in_(_DRAFT_STATUSES))
        .order_by(Post.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()
