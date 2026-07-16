"""KPI пилота (v1.0.0) — измеримый показатель реальной компании в пилоте.

Описывает KPI (текущее/целевое значение, единица, частота, статус). Только запись показателя —
AI его НЕ меняет и бизнес не меняет.

БЕЗОПАСНОСТЬ:
- KPI — только описание показателя; секретов не содержит.
"""

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Статус KPI.
PILOT_KPI_STATUSES: tuple[str, ...] = ("active", "paused", "archived")
# Частота отслеживания.
PILOT_KPI_FREQUENCIES: tuple[str, ...] = ("daily", "weekly", "monthly", "quarterly")


class PilotKPI(Base, TimestampMixin):
    """KPI пилота (per-workspace, без секретов)."""

    __tablename__ = "pilot_kpis"
    __table_args__ = (Index("ix_pilot_kpis_workspace_status", "workspace_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), default="", nullable=False)
    # daily | weekly | monthly | quarterly
    frequency: Mapped[str] = mapped_column(String(30), default="monthly", nullable=False)
    # active | paused | archived
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
