"""Сравнение сценариев (v0.7.5) — итог сопоставления вариантов решения.

Сравнивает сценарии решения (A vs B vs C) по Strategy Score и фиксирует победителя,
разницу оценок и обоснование. Append-only.

БЕЗОПАСНОСТЬ:
- сравнение — только аналитика/рекомендация; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class ScenarioComparison(Base):
    """Одно сравнение сценариев решения (per-decision, append-only, без секретов)."""

    __tablename__ = "scenario_comparisons"
    __table_args__ = ()

    id: Mapped[int] = mapped_column(primary_key=True)
    decision_id: Mapped[int] = mapped_column(
        ForeignKey("ai_decisions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # id победившего сценария (мягкая ссылка, без FK — избегаем лишних ограничений).
    winner_scenario_id: Mapped[int | None] = mapped_column(Integer, default=None)
    comparison_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    score_difference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
