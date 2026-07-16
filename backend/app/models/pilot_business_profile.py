"""Бизнес-профиль пилота (v0.9.1) — описание реальной компании для advisory-анализа.

Хранит продукты/услуги/команду/каналы продаж/описание/выручку/цель/KPI пилота. Используется как
контекст для CEO Dashboard и pilot-отчёта. Только данные профиля — ничего не выполняет.

БЕЗОПАСНОСТЬ:
- профиль — только описание бизнеса; секретов не содержит.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PilotBusinessProfile(Base, TimestampMixin):
    """Бизнес-профиль pilot-воркспейса (per-workspace, без секретов)."""

    __tablename__ = "pilot_business_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    products: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    services: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    team: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    sales_channels: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    business_description: Mapped[str | None] = mapped_column(Text, default=None)
    current_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_revenue: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    kpi: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
