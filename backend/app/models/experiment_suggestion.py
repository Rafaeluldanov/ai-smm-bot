"""Модель предложения эксперимента (worker suggestion) — v0.4.3.

Worker (или клиент через API/CLI) анализирует проект и предлагает эксперимент/тему:
что публиковать чаще, чего избегать, что перетестировать. Предложение показывается
клиенту; он может принять/отклонить/скрыть или создать A/B-эксперимент. Live-публикаций нет.

БЕЗОПАСНОСТЬ:
- ``recommendation_payload``/``source_signals`` не содержат секретов;
- строго account/project-scoped; создание эксперимента платное и идемпотентное;
- никаких live-публикаций/внешних вызовов.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.3): единые перечисления значений (Part 1 спецификации). --- #
# Держим как импортируемые кортежи, чтобы валидация/UI/тесты ссылались на один
# источник правды, а не на разрозненные строковые литералы.
SUGGESTION_STATUSES: tuple[str, ...] = (
    "proposed",
    "accepted",
    "rejected",
    "dismissed",
    "experiment_created",
    "expired",
    "failed",
    "duplicate_skipped",
)
# Статусы «живого» предложения, которое ещё видно клиенту и учитывается в лимитах.
ACTIVE_SUGGESTION_STATUSES: tuple[str, ...] = ("proposed", "accepted")

SUGGESTION_TYPES: tuple[str, ...] = (
    "publish_more",
    "avoid",
    "retest",
    "explore",
    "fill_gap",
    "cta_test",
    "media_test",
    "timing_test",
    "format_test",
    "weak_topic_fix",
)
SUGGESTION_SOURCES: tuple[str, ...] = (
    "worker",
    "manual",
    "api",
    "cli",
    "schedule",
    "learning_profile",
)
SUGGESTION_ACTIONS: tuple[str, ...] = (
    "preview",
    "create_suggestion",
    "accept",
    "dismiss",
    "reject",
    "create_experiment",
    "expire",
)


class ExperimentSuggestion(Base, TimestampMixin):
    """Предложение эксперимента/темы (proposed → accepted/rejected/experiment_created)."""

    __tablename__ = "experiment_suggestions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    # publish_more | avoid | retest | explore | fill_gap | cta_test | media_test |
    # timing_test | format_test | weak_topic_fix
    suggestion_type: Mapped[str] = mapped_column(
        String(30), index=True, default="publish_more", nullable=False
    )
    # worker | manual | api | cli | schedule | learning_profile
    source: Mapped[str] = mapped_column(String(20), index=True, default="worker", nullable=False)
    # proposed | accepted | rejected | dismissed | experiment_created | expired |
    # failed | duplicate_skipped
    status: Mapped[str] = mapped_column(String(20), index=True, default="proposed", nullable=False)
    topic: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    recommendation_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risk_flags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    suggested_cta: Mapped[str | None] = mapped_column(String(512), default=None)
    suggested_media_type: Mapped[str | None] = mapped_column(String(64), default=None)
    suggested_publish_time: Mapped[str | None] = mapped_column(String(20), default=None)
    estimated_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    worker_owner_id: Mapped[str | None] = mapped_column(String(128), default=None)
    schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="SET NULL"), index=True, default=None
    )
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_experiments.id", ondelete="SET NULL"), index=True, default=None
    )
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    rejected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    dismissed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    acted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
