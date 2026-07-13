"""Модель бакета rate-limit доставки уведомлений — v0.5.2.

Локальный DB-backed лимитер (окно + счётчик) для доставки уведомлений: per user/project/
account/channel/type/provider. Подходит для MVP; Redis-лимитер — позже. Секретов не хранит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.2). --- #
NOTIFICATION_RATE_LIMIT_SCOPES: tuple[str, ...] = (
    "user",
    "project",
    "account",
    "channel",
    "notification_type",
    "provider",
)


class NotificationRateLimitBucket(Base, TimestampMixin):
    """Бакет rate-limit доставки (окно ``window_seconds`` с ``count`` до ``limit_value``)."""

    __tablename__ = "notification_rate_limit_buckets"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    channel: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    provider: Mapped[str | None] = mapped_column(String(20), default=None)
    notification_type: Mapped[str | None] = mapped_column(String(40), default=None)
    scope: Mapped[str] = mapped_column(String(30), default="user", nullable=False)

    bucket_key: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, nullable=False
    )
    window_seconds: Mapped[int] = mapped_column(Integer, default=3600, nullable=False)
    count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    limit_value: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    bucket_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
