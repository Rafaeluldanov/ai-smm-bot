"""Результат эксперимента оптимизации (v0.8.1) — измеренный итог + валидация.

Фиксирует факт против ожидания по завершении эксперимента: actual/expected/difference, итог
валидации (success/failure/inconclusive) и аналитику. Append-only. Только измерение — ничего в
бизнесе не меняет.

БЕЗОПАСНОСТЬ:
- результат — аналитика измерения; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class ExperimentResult(Base):
    """Результат эксперимента оптимизации (append-only, без секретов)."""

    __tablename__ = "experiment_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_experiments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    actual_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    expected_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # success | failure | inconclusive
    validation_result: Mapped[str] = mapped_column(
        String(20), default="inconclusive", nullable=False
    )
    analysis: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
