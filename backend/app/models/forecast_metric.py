"""Прогноз бизнес-метрики (v0.7.6) — KPI-проекция прогноза развития бизнеса.

Одна метрика (revenue/leads/customers/…) прогноза: базовое значение, прогнозное значение,
изменение в %, уверенность и обоснование. Append-only.

БЕЗОПАСНОСТЬ:
- прогноз — модельная оценка, НЕ финансовая гарантия; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class ForecastMetric(Base):
    """Одна KPI-проекция прогноза (per-forecast, append-only, без секретов)."""

    __tablename__ = "forecast_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_id: Mapped[int] = mapped_column(
        ForeignKey("business_forecasts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # revenue | leads | customers | conversion | traffic | efficiency
    metric: Mapped[str] = mapped_column(String(20), nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    forecast_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    change_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
