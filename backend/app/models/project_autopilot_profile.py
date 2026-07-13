"""Модель профиля автопилота проекта — v0.5.6.

«Панель автопилота» проекта: клиент подключает площадки, даёт Яндекс Диск, выбирает календарь и
включает автопилот — дальше Botfleet сам пишет тексты, выбирает картинки и публикует по календарю
(если live-gates разрешены; иначе безопасно создаёт draft/needs_review). Профиль не заменяет
``CrmPublishingPlan``, а управляет им и хранит упрощённые клиентские настройки.

БЕЗОПАСНОСТЬ:
- секретов/сырых токенов не хранит (только ссылки на ресурсы и упрощённые правила);
- ``project_id`` уникален (один профиль автопилота на проект);
- включение автопилота НЕ включает глобальные live-флаги публикации.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.6, Часть 1). --- #
AUTOPILOT_STATUSES: tuple[str, ...] = (
    "draft",
    "setup_required",
    "ready",
    "running",
    "paused",
    "blocked",
    "error",
)
AUTOPILOT_MODES: tuple[str, ...] = ("full_auto", "semi_auto")
AUTOPILOT_BLOCKER_TYPES: tuple[str, ...] = (
    "no_platform_connected",
    "no_yandex_disk",
    "no_media",
    "weak_media_library",
    "no_calendar",
    "no_balance",
    "live_flags_disabled",
    "platform_credentials_missing",
    "instagram_public_url_missing",
    "review_required",
    "safety_gate_failed",
)
AUTOPILOT_STEP_KEYS: tuple[str, ...] = (
    "create_project",
    "connect_platform",
    "connect_yandex_disk",
    "sync_media",
    "choose_calendar",
    "choose_content_rules",
    "enable_autopilot",
    "first_post_ready",
)
AUTOPILOT_CLIENT_ACTIONS: tuple[str, ...] = (
    "connect_platform",
    "connect_media",
    "configure_calendar",
    "start_autopilot",
    "fix_blocker",
    "create_first_draft",
    "open_calendar",
    "open_billing",
)


class ProjectAutopilotProfile(Base, TimestampMixin):
    """Профиль автопилота проекта (одна панель на проект); управляет CrmPublishingPlan."""

    __tablename__ = "project_autopilot_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        index=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(24), index=True, default="setup_required", nullable=False
    )
    mode: Mapped[str] = mapped_column(String(16), index=True, default="full_auto", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, index=True, default=False, nullable=False)

    yandex_resource_id: Mapped[int | None] = mapped_column(default=None)
    primary_platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    calendar_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    content_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    quality_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    safety_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    setup_progress: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    active_blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    last_health_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_health_status: Mapped[str | None] = mapped_column(String(24), default=None)
    last_autopilot_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    next_planned_post_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    profile_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
