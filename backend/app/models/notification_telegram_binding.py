"""Модель привязки Telegram как канала уведомлений — v0.5.4.

Пользователь подключает Telegram: система выдаёт verification token, пользователь отправляет
боту ``/start <token>``, Botfleet сохраняет binding (chat_id/telegram_user_id). Пока live-доставка
выключена (по умолчанию) — всё работает как sandbox: реальных сообщений наружу нет.

БЕЗОПАСНОСТЬ:
- ``chat_id`` / ``telegram_user_id`` хранятся ТОЛЬКО encrypted + masked + sha256-hash;
- сырой ``chat_id`` НИКОГДА не отдаётся в API/UI;
- verification token хранится ТОЛЬКО как sha256-hash + prefix; сырой токен показывается один раз
  при создании и в логи/аудит не пишется;
- bot token в БД не хранится (только secret env).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.4, Часть 1). --- #
TELEGRAM_BINDING_STATUSES: tuple[str, ...] = (
    "draft",
    "pending_verification",
    "verified",
    "disabled",
    "suppressed",
    "revoked",
    "failed",
)
TELEGRAM_TEMPLATE_TYPES: tuple[str, ...] = (
    "review_assigned",
    "review_mentioned",
    "review_comment",
    "review_changes_requested",
    "review_approved",
    "review_rejected",
    "task_overdue",
    "post_needs_review",
    "experiment_suggestion_created",
    "experiment_winner_selected",
    "learning_profile_updated",
    "billing_balance_low",
    "digest_daily",
    "digest_weekly",
    "system_notice",
)
TELEGRAM_DELIVERY_MODES: tuple[str, ...] = ("preview", "mock", "live_blocked", "live")
TELEGRAM_PARSE_MODES: tuple[str, ...] = ("none", "markdown_v2", "html")


class NotificationTelegramBinding(Base, TimestampMixin):
    """Привязка Telegram-чата к пользователю для доставки уведомлений (sandbox по умолчанию)."""

    __tablename__ = "notification_telegram_bindings"

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

    status: Mapped[str] = mapped_column(String(24), index=True, default="draft", nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), default=None)

    # telegram_user_id / chat_id — чувствительные: encrypted + masked + hash.
    telegram_user_id_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    telegram_user_id_masked: Mapped[str | None] = mapped_column(String(64), default=None)
    telegram_user_id_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    chat_id_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    chat_id_masked: Mapped[str | None] = mapped_column(String(64), default=None)
    chat_id_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    username: Mapped[str | None] = mapped_column(String(255), default=None)

    # verification token — только hash + prefix (сырой токен не хранится).
    verification_token_hash: Mapped[str | None] = mapped_column(
        String(64), index=True, default=None
    )
    verification_token_prefix: Mapped[str | None] = mapped_column(String(16), default=None)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    binding_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
