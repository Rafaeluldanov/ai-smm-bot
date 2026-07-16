"""Бизнес-цель пилота (v1.0.0) — цель реальной компании в пилоте.

Описывает измеримую бизнес-цель (текущее/целевое значение, единица, дедлайн, приоритет, статус).
Только запись цели — AI её НЕ выполняет, бизнес не меняет.

БЕЗОПАСНОСТЬ:
- цель — только описание; секретов не содержит; внешних действий не выполняет.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Статус цели пилота.
PILOT_GOAL_STATUSES: tuple[str, ...] = ("draft", "active", "completed", "cancelled")
# Приоритет.
PILOT_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")


class PilotGoal(Base, TimestampMixin):
    """Бизнес-цель пилота (per-workspace, без секретов)."""

    __tablename__ = "pilot_goals"
    __table_args__ = (Index("ix_pilot_goals_workspace_status", "workspace_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # draft | active | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
