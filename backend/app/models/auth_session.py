"""Модель серверной сессии аутентификации (refresh + ревокация).

Хранит только ХЕШ refresh-токена (не сам токен). Сессия ревокируется при logout,
logout-all и ротации. Секреты/токены в БД не попадают.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AuthSession(Base, TimestampMixin):
    """Сессия входа пользователя (refresh-токен хранится хешем)."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    # active | revoked | expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    session_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
