"""Метрика эффективности (v0.7.9) — план vs факт по одной метрике.

Одна метрика снимка: план (target), факт (actual), разница и её %, статус и обоснование.
Append-only.

БЕЗОПАСНОСТЬ:
- метрика — аналитика; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class PerformanceMetric(Base):
    """Метрика эффективности (per-snapshot, append-only, без секретов)."""

    __tablename__ = "performance_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("performance_snapshots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # revenue | sales | leads | conversion | execution | efficiency
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difference: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    difference_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # healthy | warning | critical
    status: Mapped[str] = mapped_column(String(20), default="healthy", nullable=False)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
