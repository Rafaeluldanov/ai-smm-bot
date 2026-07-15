"""Бизнес-цель владельца (v0.7.7) — вход AI Business Planner.

Planner превращает бизнес-цель в стратегический план: анализирует текущее состояние, сравнивает
с прогнозом, находит gap, строит план, квартальные цели, KPI и roadmap. Это planning-слой.

Поток: **Business Goal → Gap Analysis → Strategic Plan → Quarter Objectives → KPI →
Milestones → Workflow Draft**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ выполняет план автоматически, НЕ меняет
  бизнес/CRM/бюджет, НЕ запускает рекламу, НЕ публикует — только планирует и советует.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Business Planner (Часть 1) ---

# Типы бизнес-целей.
GOAL_TYPES: tuple[str, ...] = (
    "revenue",
    "growth",
    "sales",
    "marketing",
    "efficiency",
    "operational",
)
# Статусы плана.
PLAN_STATUSES: tuple[str, ...] = ("draft", "generated", "reviewed", "approved", "archived")
# Статусы квартальной цели.
OBJECTIVE_STATUSES: tuple[str, ...] = ("planned", "active", "completed", "cancelled")
# Приоритеты.
PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Статусы бизнес-цели (жизненный цикл самой цели).
GOAL_STATUSES: tuple[str, ...] = ("active", "achieved", "cancelled", "archived")


class BusinessGoal(Base, TimestampMixin):
    """Бизнес-цель владельца (per-project, без секретов)."""

    __tablename__ = "business_goals"
    __table_args__ = (Index("ix_business_goals_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # revenue | growth | sales | marketing | efficiency | operational
    goal_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    target_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # active | achieved | cancelled | archived
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    # `metadata` зарезервировано SQLAlchemy → goal_metadata (в API отдаётся как "metadata").
    goal_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
