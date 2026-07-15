"""Веха плана (v0.7.7) — контрольная точка квартальной цели.

Конкретный milestone внутри квартальной цели: что и к какому сроку. Планирующий артефакт: НЕ
выполняется автоматически.

БЕЗОПАСНОСТЬ:
- веха — только план/ориентир; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PlanMilestone(Base, TimestampMixin):
    """Веха квартальной цели (per-objective, без секретов)."""

    __tablename__ = "plan_milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int] = mapped_column(
        ForeignKey("quarter_objectives.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # planned | active | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="planned", nullable=False)
    # `metadata` зарезервировано SQLAlchemy → milestone_metadata (в API отдаётся как "metadata").
    milestone_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
