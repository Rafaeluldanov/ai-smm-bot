"""Бизнес-роадмап прогноза (v0.7.6) — план развития по кварталам.

Разворачивает прогноз в квартальный roadmap: цели по кварталам, вехи, риски и рекомендации.
Это аналитический/рекомендательный артефакт.

БЕЗОПАСНОСТЬ:
- roadmap — только советы/ориентиры; НЕ выполняется автоматически; секретов не содержит.
"""

from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class BusinessRoadmap(Base, TimestampMixin):
    """Квартальный roadmap прогноза (per-forecast, без секретов)."""

    __tablename__ = "business_roadmaps"

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_id: Mapped[int] = mapped_column(
        ForeignKey("business_forecasts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    quarters: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    milestones: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommendations: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
