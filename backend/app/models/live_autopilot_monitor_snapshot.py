"""Модель снимка мониторинга live-автопилота — v0.6.1.

Снимок состояния автопилота проекта: успехи/ошибки/блокировки публикаций за окно, готовность,
баланс, открытые инциденты. Клиентский слой «что происходит» без технического шума. Это журнал
наблюдения, а не включатель live: глобальные флаги он не трогает.

БЕЗОПАСНОСТЬ:
- НЕ хранит токены/сырые payload/внутренние пути;
- только агрегаты и безопасные summary.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.1, Часть 1). --- #
LIVE_AUTOPILOT_HEALTH_STATUSES: tuple[str, ...] = (
    "healthy",
    "warning",
    "degraded",
    "paused",
    "blocked",
    "failed",
    "unknown",
)
LIVE_AUTOPILOT_SEVERITIES: tuple[str, ...] = ("info", "low", "medium", "high", "critical")
LIVE_AUTOPILOT_KILL_SWITCH_SCOPES: tuple[str, ...] = (
    "project",
    "platform",
    "full_auto",
    "telegram_rollout",
)
LIVE_AUTOPILOT_CONTROL_ACTIONS: tuple[str, ...] = (
    "pause_project_autopilot",
    "resume_project_autopilot",
    "pause_platform_live",
    "resume_platform_live",
    "acknowledge_incident",
    "resolve_incident",
    "ignore_incident",
    "run_health_check",
    "run_dry_preview",
)


class LiveAutopilotMonitorSnapshot(Base, TimestampMixin):
    """Снимок состояния мониторинга автопилота проекта (за окно наблюдения)."""

    __tablename__ = "live_autopilot_monitor_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_key: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    health_status: Mapped[str] = mapped_column(
        String(16), index=True, default="unknown", nullable=False
    )
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    total_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    published_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    blocked_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    failure_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    last_attempt_id: Mapped[int | None] = mapped_column(Integer, default=None)
    last_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    open_incident_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_incident_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    balance_units: Mapped[int | None] = mapped_column(Integer, default=None)
    approx_posts_left: Mapped[int | None] = mapped_column(Integer, default=None)
    project_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    full_auto_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)

    platform_live_statuses: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    readiness_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
