"""Модель контент-эксперимента (A/B-тест / оптимизация) — v0.4.2.

Один эксперимент = гипотеза + несколько вариантов поста (A/B/C), которые идут в очередь
ревью (НЕ live-публикация). Winner выбирается вручную клиентом или системой по
feedback + метрикам и обновляет ``ClientLearningProfile``.

БЕЗОПАСНОСТЬ:
- эксперименты строго account/project-scoped (изоляция на API/сервисном слое);
- ``experiment_metadata`` не содержит секретов; live-публикаций нет.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ContentExperiment(Base, TimestampMixin):
    """Контент-эксперимент проекта (набор вариантов + winner)."""

    __tablename__ = "content_experiments"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    # ab_test | topic_test | cta_test | media_test | timing_test | format_test
    experiment_type: Mapped[str] = mapped_column(
        String(20), default="ab_test", index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # draft | active | waiting_metrics | completed | canceled | failed
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    source_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), index=True, default=None
    )
    source_schedule_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("schedule_runs.id", ondelete="SET NULL"), default=None
    )
    # id варианта-победителя (без FK — таблица вариантов создаётся позже; ссылка мягкая).
    winner_variant_id: Mapped[int | None] = mapped_column(Integer, default=None)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    learning_profile_version: Mapped[int | None] = mapped_column(Integer, default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    experiment_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
