"""Модель дайджеста уведомлений (notification digest) — v0.5.1.

Собирает недавние уведомления пользователя в daily/weekly дайджест для внешней доставки.
В MVP реальная отправка ВЫКЛЮЧЕНА: дайджест генерируется и логируется, но не отправляется.

БЕЗОПАСНОСТЬ:
- ``subject``/``body_preview``/``body_metadata`` санитизируются на сервисном слое (без
  секретов и внутренних путей); ``notification_ids`` — только id;
- строго user/account/project-scoped.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class NotificationDigest(Base, TimestampMixin):
    """Дайджест уведомлений пользователя (daily/weekly). В MVP без реальной отправки."""

    __tablename__ = "notification_digests"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )

    frequency: Mapped[str] = mapped_column(String(20), index=True, default="daily", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="draft", nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )

    notification_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    body_preview: Mapped[str | None] = mapped_column(Text, default=None)
    body_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    delivery_log_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_delivery_logs.id", ondelete="SET NULL"), default=None
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error_message: Mapped[str | None] = mapped_column(String(512), default=None)
