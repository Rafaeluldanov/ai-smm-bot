"""Репозиторий серверных сессий аутентификации."""

from datetime import datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.auth_session import AuthSession


def create_session(db: Session, **fields: Any) -> AuthSession:
    """Создать сессию."""
    session = AuthSession(**fields)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_by_session_id(db: Session, session_id: str) -> AuthSession | None:
    """Вернуть сессию по session_id или None."""
    return db.scalars(select(AuthSession).where(AuthSession.session_id == session_id)).first()


def list_active_for_user(db: Session, user_id: int, limit: int = 100) -> list[AuthSession]:
    """Активные сессии пользователя (свежие первыми)."""
    stmt = (
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.status == "active")
        .order_by(AuthSession.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_last_seen(db: Session, session: AuthSession, when: datetime) -> AuthSession:
    """Обновить last_seen_at сессии."""
    session.last_seen_at = when
    db.commit()
    db.refresh(session)
    return session


def replace_refresh_hash(db: Session, session: AuthSession, new_hash: str) -> AuthSession:
    """Заменить хеш refresh-токена (ротация)."""
    session.refresh_token_hash = new_hash
    db.commit()
    db.refresh(session)
    return session


def revoke_session(db: Session, session: AuthSession, when: datetime) -> AuthSession:
    """Отозвать сессию."""
    session.status = "revoked"
    session.revoked_at = when
    db.commit()
    db.refresh(session)
    return session


def revoke_all_user_sessions(db: Session, user_id: int, when: datetime) -> int:
    """Отозвать все активные сессии пользователя. Возвращает число отозванных."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.status == "active")
        .values(status="revoked", revoked_at=when)
    )
    result = db.execute(stmt)
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def cleanup_expired_sessions(db: Session, now: datetime) -> int:
    """Пометить истёкшие активные сессии как expired. Возвращает число."""
    stmt = (
        update(AuthSession)
        .where(AuthSession.status == "active", AuthSession.expires_at < now)
        .values(status="expired")
    )
    result = db.execute(stmt)
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)
