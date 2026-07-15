"""Бизнес-цель (v0.7.0) — вход Autonomous Business OS / AI Executive Layer.

Владелец задаёт бизнес-цель (рост выручки/лидов/узнаваемости и т. п.) с целевым
значением и сроком. AI Executive Layer строит по ней исполнительный план и
приоритетные действия. Это верхний уровень управления — advisory + planning.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ меняет бизнес/CRM/бюджет/live сам —
  всё через Analyze → Recommend → Approve → Apply (с подтверждением).
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины Autonomous Business OS (Часть 1) ---

# Типы бизнес-целей.
BUSINESS_OBJECTIVE_TYPES: tuple[str, ...] = (
    "revenue_growth",
    "lead_growth",
    "brand_awareness",
    "efficiency",
    "retention",
    "expansion",
)
# Статусы цели.
OBJECTIVE_STATUSES: tuple[str, ...] = ("draft", "active", "completed", "paused")
# Типы приоритетов.
PRIORITY_TYPES: tuple[str, ...] = (
    "growth",
    "revenue",
    "conversion",
    "content",
    "sales",
    "efficiency",
)
# Статусы бизнес-действия.
ACTION_STATUSES: tuple[str, ...] = ("generated", "accepted", "rejected", "applied")


class BusinessObjective(Base, TimestampMixin):
    """Бизнес-цель проекта (для исполнительного плана)."""

    __tablename__ = "business_objectives"
    __table_args__ = (
        Index("ix_business_objectives_project_status", "project_id", "status"),
        Index("ix_business_objectives_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # revenue_growth | lead_growth | brand_awareness | efficiency | retention | expansion
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(40), default=None)
    deadline: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    # draft | active | completed | paused (запросы по статусу всегда project-scoped —
    # покрыты композитным индексом ix_business_objectives_project_status)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    objective_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
