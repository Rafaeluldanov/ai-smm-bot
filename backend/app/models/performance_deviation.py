"""Отклонение эффективности (v0.7.9) — значимое расхождение план/факт.

Фиксирует отклонение по метрике: тип, влияние, описание и вероятные причины. Append-only.

БЕЗОПАСНОСТЬ:
- отклонение — аналитика/диагностика; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class PerformanceDeviation(Base):
    """Отклонение эффективности (per-snapshot, append-only, без секретов)."""

    __tablename__ = "performance_deviations"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("performance_snapshots.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # positive | negative | neutral
    deviation_type: Mapped[str] = mapped_column(String(20), default="negative", nullable=False)
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    # low | medium | high | critical
    impact: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    root_causes: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
