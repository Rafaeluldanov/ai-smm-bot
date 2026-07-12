"""Модель решения о теме для слота расписания (auto topic selection) — v0.4.4.

Worker (или клиент через API/CLI) выбирает лучшую тему/CTA/формат/медиа-стратегию для
ближайшего слота расписания на основе learning profile + метрик + feedback + A/B winners +
experiment suggestions и сохраняет «почему бот выбрал эту тему». Пост создаётся только как
draft/needs_review — live-публикаций нет.

БЕЗОПАСНОСТЬ:
- ``alternatives``/``source_signals``/``decision_metadata`` не содержат секретов;
- строго account/project-scoped; никаких live-публикаций/внешних вызовов;
- дедуп по ``idempotency_key``.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.4): единые перечисления значений (Part 1 спецификации). --- #
TOPIC_DECISION_STATUSES: tuple[str, ...] = (
    "preview",
    "selected",
    "draft_created",
    "skipped",
    "failed",
    "blocked",
)
TOPIC_DECISION_SOURCES: tuple[str, ...] = (
    "learning_profile",
    "metrics",
    "ab_winner",
    "experiment_suggestion",
    "crm_category",
    "keyword_priority",
    "media_availability",
    "fallback",
)
TOPIC_DECISION_RISKS: tuple[str, ...] = (
    "low_confidence",
    "repeated_topic",
    "weak_metrics",
    "no_media",
    "missing_credentials",
    "insufficient_balance",
    "live_disabled",
    "quality_below_threshold",
    "content_gap",
    "stale_learning_profile",
)
TOPIC_DECISION_MODES: tuple[str, ...] = ("semi_auto", "full_auto", "dry_run")


class ScheduleTopicDecision(Base, TimestampMixin):
    """Решение о теме слота (preview → selected → draft_created). Live-публикаций нет."""

    __tablename__ = "schedule_topic_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    publishing_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_publishing_plans.id", ondelete="SET NULL"), index=True, default=None
    )
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="SET NULL"), index=True, default=None
    )
    experiment_suggestion_id: Mapped[int | None] = mapped_column(
        ForeignKey("experiment_suggestions.id", ondelete="SET NULL"), default=None
    )
    content_experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_experiments.id", ondelete="SET NULL"), default=None
    )

    selected_topic: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    selected_cta: Mapped[str | None] = mapped_column(String(512), default=None)
    selected_format: Mapped[str | None] = mapped_column(String(64), default=None)
    selected_media_strategy: Mapped[str | None] = mapped_column(String(64), default=None)
    selected_publish_time: Mapped[str | None] = mapped_column(String(20), default=None)

    # learning_profile | metrics | ab_winner | experiment_suggestion | crm_category |
    # keyword_priority | media_availability | fallback
    decision_source: Mapped[str] = mapped_column(
        String(40), index=True, default="fallback", nullable=False
    )
    # semi_auto | full_auto | dry_run
    decision_mode: Mapped[str] = mapped_column(String(20), default="dry_run", nullable=False)
    # preview | selected | draft_created | skipped | failed | blocked
    status: Mapped[str] = mapped_column(String(20), index=True, default="preview", nullable=False)

    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expected_quality_score: Mapped[int | None] = mapped_column(Integer, default=None)
    expected_engagement_score: Mapped[int | None] = mapped_column(Integer, default=None)
    learning_profile_version: Mapped[int | None] = mapped_column(Integer, default=None)

    alternatives: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risk_flags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    decision_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    created_by_worker_owner_id: Mapped[str | None] = mapped_column(String(128), default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
