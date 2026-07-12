"""Модель журнала доставки уведомлений (delivery log) — v0.5.1.

Фиксирует попытки доставки уведомлений по внешним каналам (email/telegram/webhook/digest).
В MVP реальная внешняя доставка ВЫКЛЮЧЕНА: mock-провайдеры пишут лог, но ничего не отправляют.

БЕЗОПАСНОСТЬ:
- НИКАКИХ сырых токенов/секретов/паролей: ``destination_masked`` только маска, а
  ``request_metadata``/``response_metadata`` санитизируются на сервисном слое;
- ``message_preview`` — короткий безопасный фрагмент (без внутренних путей);
- строго account/project/recipient-scoped (изоляция — на API/сервисном слое).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.1): единые перечисления значений (Часть 1). --- #
NOTIFICATION_DELIVERY_PROVIDERS: tuple[str, ...] = ("mock", "smtp", "telegram_bot", "webhook")
NOTIFICATION_DELIVERY_STATUSES: tuple[str, ...] = (
    "pending",
    "sent",
    "failed",
    "skipped",
    "disabled",
    "retry_scheduled",
    "canceled",
)
NOTIFICATION_DELIVERY_CHANNELS: tuple[str, ...] = ("email", "telegram", "webhook", "digest")
NOTIFICATION_DIGEST_STATUSES: tuple[str, ...] = (
    "draft",
    "generated",
    "sent",
    "skipped",
    "failed",
)
NOTIFICATION_DIGEST_FREQUENCIES: tuple[str, ...] = ("daily", "weekly")


class NotificationDeliveryLog(Base, TimestampMixin):
    """Запись о попытке доставки уведомления по внешнему каналу (в MVP — без реальной отправки)."""

    __tablename__ = "notification_delivery_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    notification_id: Mapped[int | None] = mapped_column(
        ForeignKey("app_notifications.id", ondelete="SET NULL"), index=True, default=None
    )
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    provider: Mapped[str] = mapped_column(String(20), index=True, default="mock", nullable=False)
    channel: Mapped[str] = mapped_column(String(20), index=True, default="email", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending", nullable=False)

    destination_masked: Mapped[str | None] = mapped_column(String(255), default=None)
    subject: Mapped[str | None] = mapped_column(String(255), default=None)
    message_preview: Mapped[str | None] = mapped_column(Text, default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(255), default=None)

    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    error_message: Mapped[str | None] = mapped_column(String(512), default=None)

    request_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
