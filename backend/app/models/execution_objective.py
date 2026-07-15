"""Цель исполнения (v0.7.8) — стратегическая задача плана исполнения.

Переносит квартальную цель плана (Business Planner) в исполнение с KPI, приоритетом, владельцем и
прогрессом. Coordination-артефакт: НЕ выполняется автоматически.

БЕЗОПАСНОСТЬ:
- цель исполнения — только координация/план; секретов не содержит.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ExecutionObjective(Base, TimestampMixin):
    """Цель исполнения (per-execution-plan, без секретов)."""

    __tablename__ = "execution_objectives"

    id: Mapped[int] = mapped_column(primary_key=True)
    execution_plan_id: Mapped[int] = mapped_column(
        ForeignKey("execution_plans.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    kpi: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # draft | active | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
