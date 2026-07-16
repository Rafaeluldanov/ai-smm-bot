"""Память опыта (v0.8.0) — вход AI Continuous Improvement Engine.

Engine строит цикл обучения бизнеса на истории решений и результатов: сохраняет опыт, анализирует
результаты, находит паттерны и причины провалов, создаёт улучшения и рекомендует следующий цикл.
Это learning/аналитический слой.

Поток: **Performance Result → Experience Memory → Learning Event → Pattern Analysis →
Improvement Backlog → Owner Review**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ меняет бизнес/стратегию/KPI/CRM/бюджет, НЕ
  выполняет задачи и улучшения, НЕ запускает рекламу, НЕ публикует — только учится и советует.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Continuous Improvement (Часть 1) ---

# Типы событий обучения.
LEARNING_EVENT_TYPES: tuple[str, ...] = (
    "success",
    "failure",
    "deviation",
    "improvement",
    "insight",
)
# Типы опыта.
EXPERIENCE_TYPES: tuple[str, ...] = (
    "decision",
    "strategy",
    "execution",
    "forecast",
    "performance",
)
# Типы паттернов.
PATTERN_TYPES: tuple[str, ...] = (
    "success_pattern",
    "failure_pattern",
    "optimization_pattern",
)
# Статусы улучшения.
IMPROVEMENT_STATUSES: tuple[str, ...] = (
    "identified",
    "reviewed",
    "accepted",
    "rejected",
    "completed",
)
# Приоритеты.
PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Итоги опыта.
OUTCOMES: tuple[str, ...] = ("success", "failure", "neutral")


class ExperienceMemory(Base, TimestampMixin):
    """Единица опыта бизнеса (per-project, без секретов)."""

    __tablename__ = "experience_memories"
    __table_args__ = (
        Index("ix_experience_memories_project_type", "project_id", "experience_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # decision | strategy | execution | forecast | performance
    experience_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # id исходной сущности (мягкая ссылка, без FK — кросс-слой).
    source_id: Mapped[int | None] = mapped_column(Integer, default=None)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    expected_result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    actual_result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # success | failure | neutral
    outcome: Mapped[str] = mapped_column(String(20), default="neutral", nullable=False)
    lessons: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
