"""Репозиторий журнала согласования постов (PostReviewAction).

Только доступ к данным: создание записей действий и их чтение по посту.
Бизнес-правила переходов и смена статуса живут в ``post_review_service``.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.post_review_action import PostReviewAction
from app.schemas.post_review import PostReviewActionCreate


def create_review_action(db: Session, data: PostReviewActionCreate) -> PostReviewAction:
    """Создать запись действия согласования."""
    action = PostReviewAction(**data.model_dump())
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def list_review_actions(
    db: Session, post_id: int, limit: int = 100, offset: int = 0
) -> list[PostReviewAction]:
    """Вернуть действия по посту в хронологическом порядке (старые → новые)."""
    stmt = (
        select(PostReviewAction)
        .where(PostReviewAction.post_id == post_id)
        .order_by(PostReviewAction.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def get_last_review_action(db: Session, post_id: int) -> PostReviewAction | None:
    """Вернуть последнее действие по посту или None."""
    stmt = (
        select(PostReviewAction)
        .where(PostReviewAction.post_id == post_id)
        .order_by(PostReviewAction.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def count_review_actions(db: Session, post_id: int) -> int:
    """Посчитать число действий согласования по посту."""
    stmt = (
        select(func.count())
        .select_from(PostReviewAction)
        .where(PostReviewAction.post_id == post_id)
    )
    return db.scalar(stmt) or 0
