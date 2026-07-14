"""Модель попытки production-теста Telegram-runbook — v0.6.3.

Клиентская запись «опубликовать тестовый пост»: preview → confirmed → sending → published/failed.
Реальная отправка делегируется существующему TelegramLiveRolloutService (все safety-gates). Это
клиентский журнал поверх технического LivePublishAttempt (его создаёт rollout-сервис).

БЕЗОПАСНОСТЬ: не хранит токены/сырые payload/внутренние пути — только безопасный превью-сниппет.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.3) --- #
TELEGRAM_LIVE_RUN_ATTEMPT_STATUSES: tuple[str, ...] = (
    "preview",
    "blocked",
    "confirmed",
    "sending",
    "published",
    "failed",
)


class TelegramLiveRunAttempt(Base, TimestampMixin):
    """Попытка production-теста Telegram-runbook (preview/publish)."""

    __tablename__ = "telegram_live_run_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    runbook_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("telegram_live_runbooks.id", ondelete="CASCADE"),
        default=None,
        index=True,
    )
    post_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    publication_id: Mapped[int | None] = mapped_column(Integer, default=None)
    live_publish_attempt_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)

    status: Mapped[str] = mapped_column(String(16), index=True, default="preview", nullable=False)
    confirmation_text: Mapped[str | None] = mapped_column(String(64), default=None)
    payload_preview: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    external_post_id: Mapped[str | None] = mapped_column(String(255), default=None)
    external_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
