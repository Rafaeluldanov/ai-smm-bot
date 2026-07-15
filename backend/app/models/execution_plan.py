"""План исполнения (v0.7.8) — вход AI Execution Coordinator.

Coordinator берёт утверждённый стратегический план (Business Planner) и превращает его в
управляемую систему исполнения: цели → задачи → владельцы → сроки → прогресс → блокеры →
AI-координация. Это coordination-слой.

Поток: **Approved Strategic Plan → Execution Plan → Objectives → Tasks → Owners →
Progress → AI Coordination**.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ выполняет задачи автоматически, НЕ меняет
  бизнес/CRM/бюджет, НЕ запускает рекламу, НЕ публикует — только координирует и советует.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Execution Coordinator (Часть 1) ---

# Статусы плана/цели исполнения.
EXECUTION_STATUSES: tuple[str, ...] = ("draft", "active", "paused", "completed", "cancelled")
# Статусы задачи исполнения.
EXECUTION_TASK_STATUSES: tuple[str, ...] = (
    "pending",
    "assigned",
    "in_progress",
    "blocked",
    "completed",
    "cancelled",
)
# Приоритеты исполнения.
EXECUTION_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Типы зависимостей.
DEPENDENCY_TYPES: tuple[str, ...] = ("task", "objective", "external")


class ExecutionPlan(Base, TimestampMixin):
    """План исполнения стратегического плана (per-project, без секретов)."""

    __tablename__ = "execution_plans"
    __table_args__ = (Index("ix_execution_plans_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Исходный стратегический план (Business Planner). SET NULL — исполнение переживает удаление.
    strategic_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategic_plans.id", ondelete="SET NULL"), index=True, default=None
    )
    # draft | active | paused | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # `metadata` зарезервировано SQLAlchemy → plan_metadata (в API отдаётся как "metadata").
    plan_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
