"""Модель отписки/opt-out от уведомлений — v0.5.2.

Пользователь может отписаться от внешней доставки: глобально, по аккаунту, проекту, типу
уведомления или каналу. Активный opt-out блокирует внешнюю доставку (in-app по умолчанию не
трогаем). Секретов/сырых адресов не хранит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.2): единые перечисления (Часть 1). --- #
NOTIFICATION_OPT_OUT_SCOPES: tuple[str, ...] = (
    "global",
    "account",
    "project",
    "notification_type",
    "channel",
)
NOTIFICATION_OPT_OUT_STATUSES: tuple[str, ...] = ("active", "revoked")


class NotificationOptOut(Base, TimestampMixin):
    """Отписка пользователя от внешней доставки (scope: global/account/project/type/channel)."""

    __tablename__ = "notification_opt_outs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    channel: Mapped[str | None] = mapped_column(String(20), index=True, default=None)
    notification_type: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    scope: Mapped[str] = mapped_column(String(30), index=True, default="global", nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[str] = mapped_column(String(20), index=True, default="active", nullable=False)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    opt_out_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
