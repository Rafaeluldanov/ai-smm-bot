"""Модель внутреннего (in-app) уведомления Botfleet — v0.5.0.

Централизованные уведомления: назначения, упоминания, запросы правок, просрочки, статусы
постов/экспериментов, worker-события. Доставка ТОЛЬКО внутренняя (in-app); внешняя (email/
webhook/push) выключена по умолчанию и в MVP не отправляется.

БЕЗОПАСНОСТЬ:
- ``title``/``message``/``notification_metadata`` санитизируются на сервисном слое (без
  секретов, токенов и внутренних путей к файлам);
- строго account/project/recipient-scoped (изоляция — на API/сервисном слое).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.0): единые перечисления значений (Часть 1). --- #
NOTIFICATION_CHANNELS: tuple[str, ...] = ("in_app", "email", "digest", "webhook")
NOTIFICATION_STATUSES: tuple[str, ...] = ("unread", "read", "archived", "dismissed", "failed")
NOTIFICATION_TYPES: tuple[str, ...] = (
    "review_assigned",
    "review_mentioned",
    "review_comment",
    "review_changes_requested",
    "review_approved",
    "review_rejected",
    "review_applied",
    "task_overdue",
    "post_needs_review",
    "post_approved",
    "post_rejected",
    "experiment_suggestion_created",
    "experiment_winner_selected",
    "learning_profile_updated",
    "billing_balance_low",
    "worker_attention_needed",
    "system_notice",
)
NOTIFICATION_PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "urgent")
MENTION_STATUSES: tuple[str, ...] = ("resolved", "unresolved", "notified", "ignored")
SLA_STATUSES: tuple[str, ...] = ("ok", "due_soon", "overdue", "critical")


class AppNotification(Base, TimestampMixin):
    """Внутреннее уведомление пользователю (in-app). Внешней доставки в MVP нет."""

    __tablename__ = "app_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, default=None
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )

    notification_type: Mapped[str] = mapped_column(
        String(40), index=True, default="system_notice", nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), default="in_app", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="unread", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), index=True, default="normal", nullable=False)

    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    entity_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    action_url: Mapped[str | None] = mapped_column(String(512), default=None)

    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_delivery_error: Mapped[str | None] = mapped_column(String(512), default=None)
    notification_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
