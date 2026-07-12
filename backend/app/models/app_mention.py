"""Модель упоминания (@mention) в комментариях/сущностях Botfleet — v0.5.0.

Упоминание (`@email`, `@username`, `@user_id:123`) создаётся из текста комментария. Если
пользователь найден — статус ``resolved``/``notified`` и создаётся уведомление; если не найден —
``unresolved`` (основное действие НЕ падает). Внешнего поиска пользователей нет.

БЕЗОПАСНОСТЬ:
- ``mentioned_text``/``mention_metadata`` санитизируются на сервисном слое (без секретов/путей);
- строго account/project-scoped (изоляция — на API/сервисном слое).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AppMention(Base, TimestampMixin):
    """Упоминание пользователя в комментарии/сущности. unresolved не роняет основное действие."""

    __tablename__ = "app_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    source_entity_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    source_entity_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    comment_id: Mapped[int | None] = mapped_column(Integer, default=None)

    mentioned_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentioned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    status: Mapped[str] = mapped_column(
        String(20), index=True, default="unresolved", nullable=False
    )
    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_notifications.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    mention_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
