"""Модель настроек уведомлений пользователя — v0.5.0.

По умолчанию включён только внутренний канал (``in_app``). Каналы email/digest/webhook
выключены, пока нет реальной внешней доставки. Настройки можно задавать per-type.

БЕЗОПАСНОСТЬ:
- ``quiet_hours``/``preference_metadata`` санитизируются на сервисном слое;
- строго user/account-scoped.
"""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

DIGEST_FREQUENCIES: tuple[str, ...] = ("never", "daily", "weekly")


class NotificationPreference(Base, TimestampMixin):
    """Настройка уведомлений пользователя по каналу и (опционально) типу."""

    __tablename__ = "notification_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    channel: Mapped[str] = mapped_column(String(20), index=True, default="in_app", nullable=False)
    notification_type: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    digest_frequency: Mapped[str | None] = mapped_column(String(20), default=None)
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    preference_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
