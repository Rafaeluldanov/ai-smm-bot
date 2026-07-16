"""Элемент оптимизации (v0.8.1) — оценённое и приоритизированное улучшение.

Превращает элемент Improvement Backlog (v0.8.0) в оцениваемую единицу оптимизации: считает
Optimization Score (impact × confidence − cost − risk), приоритет и статус жизненного цикла.
Только оценка и приоритизация — улучшение НЕ применяется автоматически.

БЕЗОПАСНОСТЬ:
- optimization — только оценка/приоритет; НЕ меняет бизнес/KPI/CRM/бюджет; секретов не содержит.
"""

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Статус элемента оптимизации.
OPTIMIZATION_STATUSES: tuple[str, ...] = (
    "identified",
    "planned",
    "running",
    "completed",
    "cancelled",
)
# Статус эксперимента оптимизации.
EXPERIMENT_STATUSES: tuple[str, ...] = (
    "draft",
    "approved",
    "running",
    "completed",
    "failed",
)
# Итог валидации эксперимента.
VALIDATION_RESULTS: tuple[str, ...] = ("success", "failure", "inconclusive")
# Приоритет оптимизации.
PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")


class OptimizationItem(Base, TimestampMixin):
    """Оценённое улучшение (per-project, без секретов)."""

    __tablename__ = "optimization_items"
    __table_args__ = (Index("ix_optimization_items_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Улучшение-источник (SET NULL — оптимизация переживает удаление улучшения).
    improvement_id: Mapped[int | None] = mapped_column(
        ForeignKey("improvement_items.id", ondelete="SET NULL"), index=True, default=None
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # Составляющие оценки (0..100).
    impact_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    cost_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Итоговый Optimization Score (0..100).
    optimization_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # identified | planned | running | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="identified", nullable=False)
