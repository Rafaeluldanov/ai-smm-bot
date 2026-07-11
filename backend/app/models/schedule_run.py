"""Модель прогона расписания (schedule run / execution log).

Хранит факт обработки due-задачи расписания движком автоматизации: что бот сделал
(создал draft), пропустил или на какой ошибке остановился. НЕ живая публикация —
создаётся только draft/needs_review + PostPublication в pending/scheduled.

БЕЗОПАСНОСТЬ: ``run_metadata`` НЕ содержит секретов/токенов (только план/статус/units).
Повтор одного и того же due-слота защищён ``idempotency_key`` (unique).
"""

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ScheduleRun(Base, TimestampMixin):
    """Один обработанный due-слот расписания (plan × platform × date × time)."""

    __tablename__ = "schedule_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform_key: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    publishing_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("crm_publishing_plans.id", ondelete="SET NULL"), default=None
    )
    schedule_key: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Дата слота (YYYY-MM-DD) и плановое время (HH:MM).
    run_date: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    planned_time: Mapped[str | None] = mapped_column(String(10), default=None)
    # planned | skipped | draft_created | failed | insufficient_balance |
    # missing_credentials | live_disabled
    status: Mapped[str] = mapped_column(String(30), default="planned", index=True, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), default=None
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_publications.id", ondelete="SET NULL"), default=None
    )
    units_estimated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    units_charged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    # --- Автоматизация / обучение (v0.4.0) ---
    # semi_auto | full_auto — режим, в котором обрабатывался слот.
    automation_mode: Mapped[str | None] = mapped_column(String(20), default=None)
    # Была ли попытка авто-публикации (full_auto).
    auto_publish_attempted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Причина, по которой авто-публикация не состоялась (напр. live_disabled,
    # quality_score_below_threshold, needs_first_review, insufficient_balance).
    auto_publish_blocked_reason: Mapped[str | None] = mapped_column(String(64), default=None)
    # Версия профиля обучения, использованного при генерации.
    learning_profile_version: Mapped[int | None] = mapped_column(Integer, default=None)
    # Оценка качества контента (0..100) на момент прогона.
    quality_score: Mapped[int | None] = mapped_column(Integer, default=None)
    # Оценка безопасности контента (0..100) на момент прогона.
    safety_score: Mapped[int | None] = mapped_column(Integer, default=None)
