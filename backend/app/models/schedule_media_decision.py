"""Модель решения о медиа для слота расписания (auto media selection) — v0.4.5.

Worker (или клиент через API/CLI) выбирает media strategy и конкретные media assets для
ближайшего слота на основе темы (topic decision) + тегов + платформы + learning profile +
A/B winners + метрик + доступности медиа и сохраняет «почему бот выбрал эти медиа». Пост
создаётся только как draft/needs_review — live-публикаций нет; публичные ссылки автоматически
не создаются.

БЕЗОПАСНОСТЬ:
- ``alternatives``/``source_signals``/``decision_metadata`` не содержат секретов и внутренних
  путей к файлам;
- строго account/project-scoped; никаких live-публикаций/внешних вызовов;
- дедуп по ``idempotency_key``.
"""

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.5): единые перечисления значений (Part 1 спецификации). --- #
MEDIA_DECISION_STATUSES: tuple[str, ...] = (
    "preview",
    "selected",
    "applied_to_draft",
    "skipped",
    "failed",
    "blocked",
)
MEDIA_DECISION_SOURCES: tuple[str, ...] = (
    "topic_decision",
    "learning_profile",
    "media_tags",
    "media_availability",
    "ab_winner",
    "metrics",
    "manual_category",
    "fallback",
)
MEDIA_STRATEGIES: tuple[str, ...] = (
    "text_only",
    "single_image",
    "media_group",
    "carousel_ready",
    "video_later",
    "no_media_available",
)
MEDIA_DECISION_RISKS: tuple[str, ...] = (
    "no_media",
    "low_confidence",
    "repeated_media",
    "platform_requires_public_url",
    "media_proxy_not_https",
    "heic_conversion_needed",
    "too_many_images",
    "video_not_supported",
    "missing_media_tags",
    "weak_media_match",
)


class ScheduleMediaDecision(Base, TimestampMixin):
    """Решение о медиа слота (preview → selected → applied_to_draft). Live-публикаций нет."""

    __tablename__ = "schedule_media_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    publishing_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_publishing_plans.id", ondelete="SET NULL"), default=None
    )
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="SET NULL"), index=True, default=None
    )
    schedule_topic_decision_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_topic_decisions.id", ondelete="SET NULL"), index=True, default=None
    )

    # text_only | single_image | media_group | carousel_ready | video_later | no_media_available
    selected_strategy: Mapped[str] = mapped_column(
        String(32), index=True, default="text_only", nullable=False
    )
    selected_media_asset_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    selected_media_variant_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    selected_media_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    selected_media_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    needs_public_image_url: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    media_proxy_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    public_link_ids: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    # topic_decision | learning_profile | media_tags | media_availability | ab_winner |
    # metrics | manual_category | fallback
    decision_source: Mapped[str] = mapped_column(
        String(40), index=True, default="fallback", nullable=False
    )
    # preview | selected | applied_to_draft | skipped | failed | blocked
    status: Mapped[str] = mapped_column(String(20), index=True, default="preview", nullable=False)

    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expected_media_score: Mapped[int | None] = mapped_column(Integer, default=None)
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
