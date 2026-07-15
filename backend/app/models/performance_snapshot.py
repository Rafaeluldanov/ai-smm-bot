"""Снимок эффективности (v0.7.9) — вход AI Performance Intelligence Engine.

Engine измеряет эффективность исполнения бизнес-плана: собирает фактические результаты, сравнивает
с планом, считает performance score, находит отклонения, определяет причины и советует улучшения.
Это аналитический слой.

Поток: **Execution Plan → Performance Snapshot → Actual vs Target → Deviation Analysis →
Recommendations**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ меняет планы/KPI/CRM/бюджет, НЕ выполняет задачи и
  рекомендации, НЕ запускает рекламу, НЕ публикует — только измеряет и советует.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Performance Intelligence (Часть 1) ---

# Статусы эффективности.
PERFORMANCE_STATUSES: tuple[str, ...] = ("healthy", "warning", "critical")
# Типы метрик.
METRIC_TYPES: tuple[str, ...] = (
    "revenue",
    "sales",
    "leads",
    "conversion",
    "execution",
    "efficiency",
)
# Типы отклонений.
DEVIATION_TYPES: tuple[str, ...] = ("positive", "negative", "neutral")
# Уровни влияния.
IMPACT_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")


class PerformanceSnapshot(Base, TimestampMixin):
    """Снимок эффективности исполнения (per-project, без секретов)."""

    __tablename__ = "performance_snapshots"
    __table_args__ = (Index("ix_performance_snapshots_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Исходный план исполнения (Execution Coordinator). SET NULL — снимок переживает удаление.
    execution_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="SET NULL"), index=True, default=None
    )
    # healthy | warning | critical
    status: Mapped[str] = mapped_column(String(20), default="healthy", nullable=False)
    performance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    target_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    actual_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
