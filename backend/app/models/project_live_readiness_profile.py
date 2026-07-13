"""Модель готовности проекта к реальной автопубликации — v0.5.9.

Production live autopost audit: хранит состояние готовности проекта к реальной автопубликации по
календарю. Это НЕ включатель live: реальная публикация по-прежнему требует глобальных
``*_LIVE_PUBLISHING_ENABLED`` флагов (управляются администратором). Профиль лишь фиксирует
per-project переключатели и результат проверок; сам он live-флаги НЕ включает и НЕ обходит.

БЕЗОПАСНОСТЬ:
- секретов/сырых токенов не хранит;
- не заменяет и не обходит глобальные live-флаги;
- включение live требует явного подтверждения и порога готовности.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.9, Часть 1). --- #
LIVE_READINESS_STATUSES: tuple[str, ...] = (
    "not_checked",
    "ready",
    "not_ready",
    "blocked",
    "warning",
    "failed",
)
LIVE_READINESS_SCOPES: tuple[str, ...] = (
    "project",
    "platform",
    "autopilot",
    "schedule",
    "media",
    "billing",
    "security",
)
LIVE_AUTOPOST_MODES: tuple[str, ...] = (
    "disabled",
    "dry_run_only",
    "semi_auto_required",
    "full_auto_allowed",
    "live_allowed",
)
LIVE_READINESS_BLOCKER_TYPES: tuple[str, ...] = (
    "global_live_flag_disabled",
    "project_live_disabled",
    "platform_live_disabled",
    "platform_credentials_missing",
    "platform_check_failed",
    "no_autopilot_profile",
    "autopilot_not_running",
    "no_calendar",
    "no_yandex_disk",
    "no_media",
    "weak_media_library",
    "no_public_image_url",
    "instagram_public_url_missing",
    "insufficient_balance",
    "no_billing_account",
    "schedule_missing",
    "safety_gate_failed",
    "tenant_access_failed",
    "notification_not_configured",
    "unknown",
)
LIVE_CONFIRMATION_TYPES: tuple[str, ...] = (
    "enable_project_live",
    "enable_platform_live",
    "enable_full_auto_live",
    "disable_live",
    "acknowledge_risk",
)


class ProjectLiveReadinessProfile(Base, TimestampMixin):
    """Готовность проекта к реальной автопубликации (одна панель на проект)."""

    __tablename__ = "project_live_readiness_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    autopilot_profile_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("project_autopilot_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), index=True, default="not_checked", nullable=False
    )
    live_mode: Mapped[str] = mapped_column(
        String(24), index=True, default="disabled", nullable=False
    )
    project_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    full_auto_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    last_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    last_check_status: Mapped[str | None] = mapped_column(String(16), default=None)
    readiness_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    checklist: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    platform_statuses: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    billing_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    media_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    schedule_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    security_status: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    disabled_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    profile_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
