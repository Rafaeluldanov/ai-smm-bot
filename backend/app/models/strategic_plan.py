"""Стратегический план (v0.7.7) — план достижения бизнес-цели.

Строится из gap-анализа (текущее состояние vs цель) с учётом прогноза (Forecasting), решений
(Decision Engine) и операционного состояния (Operations Center). Аналитический/планирующий
артефакт: НЕ выполняется автоматически.

БЕЗОПАСНОСТЬ:
- план — только рекомендация; approve/convert меняют лишь статус / создают ЧЕРНОВИК процесса;
  секретов не содержит.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class StrategicPlan(Base, TimestampMixin):
    """Стратегический план бизнес-цели (per-goal, без секретов)."""

    __tablename__ = "strategic_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(
        ForeignKey("business_goals.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # draft | generated | reviewed | approved | archived
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    gap_analysis: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
