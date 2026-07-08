"""Репозиторий пользователей SaaS-платформы."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    """Вернуть пользователя по id или None."""
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> User | None:
    """Вернуть пользователя по email (без учёта регистра) или None."""
    stmt = select(User).where(func.lower(User.email) == email.strip().lower())
    return db.scalars(stmt).first()


def create_user(
    db: Session,
    email: str,
    password_hash: str,
    full_name: str | None = None,
    is_superuser: bool = False,
) -> User:
    """Создать пользователя (email нормализуется к нижнему регистру)."""
    user = User(
        email=email.strip().lower(),
        password_hash=password_hash,
        full_name=full_name,
        is_active=True,
        is_superuser=is_superuser,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
