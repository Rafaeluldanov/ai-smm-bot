"""Модель аудит-лога SaaS: кто/что/когда сделал (без секретов).

Лёгкая основа аудита действий: регистрация/логин, проекты, платформы, расписания,
аналитика, биллинг, OAuth. Метаданные санитизируются (секреты не сохраняются).
"""

from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AuditLogEntry(Base, TimestampMixin):
    """Запись аудита действия пользователя/системы (created_at из TimestampMixin)."""

    __tablename__ = "audit_log_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64), default=None)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    entry_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
