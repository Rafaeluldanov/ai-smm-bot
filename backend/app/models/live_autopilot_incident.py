"""Модель инцидента live-автопилота — v0.6.1.

Проблема автопилота (повторные сбои публикаций, блокировки, низкий баланс и т.п.). Инциденты не
ломают основную работу; дают клиенту понятный «что исправить» и поддерживают kill switch/pause/
resume. Инцидент — журнал наблюдения, а не включатель live: глобальные флаги он не трогает.

БЕЗОПАСНОСТЬ:
- НЕ хранит токены/сырые payload/внутренние пути;
- только безопасные заголовки/сообщения/метаданные.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.1, Часть 1). --- #
LIVE_AUTOPILOT_INCIDENT_STATUSES: tuple[str, ...] = (
    "open",
    "acknowledged",
    "resolved",
    "ignored",
    "auto_paused",
    "failed",
)
LIVE_AUTOPILOT_INCIDENT_TYPES: tuple[str, ...] = (
    "repeated_publish_failures",
    "live_blocked",
    "balance_low",
    "platform_error",
    "media_error",
    "readiness_failed",
    "duplicate_attempt",
    "unexpected_exception",
    "safety_gate_failed",
    "external_api_error",
    "unknown",
)


class LiveAutopilotIncident(Base, TimestampMixin):
    """Инцидент автопилота (проблема, требующая внимания клиента/администратора)."""

    __tablename__ = "live_autopilot_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_key: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    incident_type: Mapped[str] = mapped_column(
        String(32), index=True, default="unknown", nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), index=True, default="open", nullable=False)
    severity: Mapped[str] = mapped_column(String(16), index=True, default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    source_entity_type: Mapped[str | None] = mapped_column(String(48), default=None)
    source_entity_id: Mapped[str | None] = mapped_column(String(64), default=None)
    live_publish_attempt_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    post_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    publication_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    schedule_run_id: Mapped[int | None] = mapped_column(Integer, default=None)
    autopilot_run_id: Mapped[int | None] = mapped_column(Integer, default=None)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    occurrences: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    acknowledged_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resolved_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ignored_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    auto_paused: Mapped[bool] = mapped_column(default=False, nullable=False)
    auto_pause_reason: Mapped[str | None] = mapped_column(String(64), default=None)
    recommended_action: Mapped[str | None] = mapped_column(String(255), default=None)
    incident_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
