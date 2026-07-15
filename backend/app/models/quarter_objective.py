"""Квартальная цель (v0.7.7) — цель квартала в стратегическом плане.

Разбивает план на кварталы (Q1–Q4) с KPI и приоритетом. Планирующий артефакт: НЕ выполняется
автоматически.

БЕЗОПАСНОСТЬ:
- цель квартала — только план/ориентир; секретов не содержит.
"""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class QuarterObjective(Base, TimestampMixin):
    """Квартальная цель стратегического плана (per-plan, без секретов)."""

    __tablename__ = "quarter_objectives"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("strategic_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Q1 | Q2 | Q3 | Q4
    quarter: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    kpi: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # planned | active | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)
