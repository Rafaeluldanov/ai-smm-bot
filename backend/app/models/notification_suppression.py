"""Модель подавления доставки (suppression) — v0.5.2.

Если внешняя доставка по каналу многократно падает (email/telegram/webhook), канал временно
подавляется. НЕ хранит сырой адрес — только hash/masked. Пользователь видит причину и может
сбросить suppression вручную.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.2). --- #
NOTIFICATION_SUPPRESSION_REASONS: tuple[str, ...] = (
    "user_unsubscribed",
    "preference_disabled",
    "destination_unverified",
    "too_many_failures",
    "rate_limited",
    "external_delivery_disabled",
    "channel_live_disabled",
    "missing_destination",
    "invalid_destination",
    "admin_disabled",
)
NOTIFICATION_SUPPRESSION_STATUSES: tuple[str, ...] = ("active", "cleared", "expired")


class NotificationSuppression(Base, TimestampMixin):
    """Временное подавление доставки по каналу/адресу из-за ошибок (без сырого адреса)."""

    __tablename__ = "notification_suppressions"

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
    channel: Mapped[str] = mapped_column(String(20), index=True, default="email", nullable=False)
    provider: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    destination_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    reason: Mapped[str] = mapped_column(String(40), default="too_many_failures", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="active", nullable=False)

    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    suppressed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    cleared_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    suppression_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
