"""Модель лога входящих Telegram-обновлений (webhook/polling sandbox) — v0.5.5.

Botfleet принимает Telegram Update в sandbox-endpoint (`POST /notification-telegram/webhook`),
парсит его и, если это ``/start <token>``, автоматически верифицирует привязку. История апдейтов
пишется сюда. Реальных исходящих Telegram-сообщений нет; реальные Telegram API-вызовы выключены.

БЕЗОПАСНОСТЬ:
- сырой ``chat_id`` / ``telegram_user_id`` НЕ хранятся — только sha256-hash + маска в тексте;
- verification token в тексте ``/start`` МАСКИРУЕТСЯ (в text_preview и raw_update_sanitized);
- bot token / webhook secret в логе не хранятся;
- ``raw_update_sanitized`` — очищенная копия апдейта (без секретов и сырых id).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.5, Часть 1). --- #
TELEGRAM_UPDATE_STATUSES: tuple[str, ...] = (
    "received",
    "processed",
    "ignored",
    "failed",
    "verified_binding",
    "duplicate",
    "invalid_secret",
)
TELEGRAM_UPDATE_TYPES: tuple[str, ...] = (
    "message",
    "callback_query",
    "edited_message",
    "unknown",
)
TELEGRAM_BOT_COMMANDS: tuple[str, ...] = ("start", "help", "status", "unknown")
TELEGRAM_WEBHOOK_MODES: tuple[str, ...] = ("disabled", "sandbox", "live_blocked", "live")
TELEGRAM_POLLING_MODES: tuple[str, ...] = ("disabled", "dry_run", "live_blocked", "live")


class NotificationTelegramUpdateLog(Base, TimestampMixin):
    """Запись входящего Telegram-обновления (webhook/polling sandbox), без сырых id/токенов."""

    __tablename__ = "notification_telegram_update_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    binding_id: Mapped[int | None] = mapped_column(
        ForeignKey("notification_telegram_bindings.id", ondelete="SET NULL"),
        index=True,
        default=None,
    )

    update_id: Mapped[int | None] = mapped_column(Integer, index=True, default=None)
    update_type: Mapped[str] = mapped_column(
        String(24), index=True, default="unknown", nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), index=True, default="received", nullable=False)
    command: Mapped[str | None] = mapped_column(String(24), index=True, default=None)

    chat_id_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    telegram_user_id_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    username: Mapped[str | None] = mapped_column(String(255), default=None)
    text_preview: Mapped[str | None] = mapped_column(String(512), default=None)

    raw_update_sanitized: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    result_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), default=None)

    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
