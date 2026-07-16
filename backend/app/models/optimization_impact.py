"""Влияние оптимизации (v0.8.2) — отслеживание impact улучшения.

Связывает governance-запись (и опционально эксперимент) с ожидаемым и фактическим влиянием,
статусом измерения и impact_score. Только измерение/отслеживание — бизнес не меняет.

БЕЗОПАСНОСТЬ:
- impact — аналитика влияния; секретов не содержит.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class OptimizationImpact(Base, TimestampMixin):
    """Impact governance-записи (per-governance, без секретов)."""

    __tablename__ = "optimization_impacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    governance_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_governances.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Эксперимент-источник (SET NULL — impact переживает удаление эксперимента).
    experiment_id: Mapped[int | None] = mapped_column(
        ForeignKey("optimization_experiments.id", ondelete="SET NULL"), index=True, default=None
    )
    # unknown | measuring | positive | neutral | negative
    status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    actual_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
