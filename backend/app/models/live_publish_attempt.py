"""Модель попытки реальной live-публикации — v0.6.0 (Telegram-first live rollout).

История live/dry-run попыток автопилота: что произошло, какие гейты прошли, был ли реальный вызов,
списались ли деньги. Это журнал/доказательство безопасности, а не включатель live: реальная
отправка по-прежнему требует глобальных ``*_LIVE_PUBLISHING_ENABLED`` + per-project/per-platform
live + подтверждения.

БЕЗОПАСНОСТЬ:
- НЕ хранит токены и сырые payload с секретами (только безопасные summary);
- НЕ хранит внутренние пути к медиа;
- заблокированная/dry-run попытка не списывает деньги (фиксируется ``balance_ok``/статусом).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.0, Часть 1). --- #
LIVE_ROLLOUT_STATUSES: tuple[str, ...] = (
    "draft",
    "ready",
    "enabled",
    "paused",
    "blocked",
    "failed",
)
LIVE_PUBLISH_ATTEMPT_STATUSES: tuple[str, ...] = (
    "preview",
    "blocked",
    "skipped",
    "attempted",
    "published",
    "failed",
)
LIVE_PUBLISH_ATTEMPT_MODES: tuple[str, ...] = (
    "dry_run",
    "live_blocked",
    "live_if_allowed",
    "live",
)
LIVE_PUBLISH_TRIGGERS: tuple[str, ...] = (
    "manual_preview",
    "manual_test",
    "manual_run_once",
    "autopilot_due",
    "schedule_due",
    "retry",
)
LIVE_ROLLOUT_BLOCKER_TYPES: tuple[str, ...] = (
    "global_live_flag_disabled",
    "project_live_disabled",
    "platform_live_disabled",
    "full_auto_live_disabled",
    "readiness_not_ready",
    "telegram_token_missing",
    "telegram_channel_missing",
    "post_missing",
    "publication_missing",
    "balance_insufficient",
    "safety_gate_failed",
    "duplicate_attempt",
    "external_call_blocked",
    "unknown",
)
TELEGRAM_ROLLOUT_STEPS: tuple[str, ...] = (
    "check_connection",
    "check_readiness",
    "check_global_flag",
    "check_project_platform_flags",
    "check_post",
    "preview_payload",
    "check_balance",
    "attempt_publish",
    "record_result",
    "notify",
)


class LivePublishAttempt(Base, TimestampMixin):
    """Одна попытка live/dry-run публикации (журнал безопасности live rollout)."""

    __tablename__ = "live_publish_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    post_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    publication_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    schedule_run_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    autopilot_run_id: Mapped[int | None] = mapped_column(Integer, default=None)
    readiness_profile_id: Mapped[int | None] = mapped_column(Integer, default=None)
    platform_readiness_id: Mapped[int | None] = mapped_column(Integer, default=None)

    trigger: Mapped[str] = mapped_column(
        String(24), index=True, default="manual_preview", nullable=False
    )
    mode: Mapped[str] = mapped_column(String(24), index=True, default="dry_run", nullable=False)
    status: Mapped[str] = mapped_column(String(16), index=True, default="preview", nullable=False)

    global_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    project_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    platform_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    full_auto_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    readiness_ready: Mapped[bool] = mapped_column(default=False, nullable=False)
    balance_ok: Mapped[bool] = mapped_column(default=False, nullable=False)
    live_attempted: Mapped[bool] = mapped_column(default=False, nullable=False)

    external_post_id: Mapped[str | None] = mapped_column(String(128), default=None)
    external_url: Mapped[str | None] = mapped_column(String(512), default=None)
    request_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    response_summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), default=None, unique=True, index=True
    )
    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    attempt_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
