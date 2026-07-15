"""Задача исполнения (v0.7.8) — конкретная задача цели исполнения.

Разбивает цель исполнения на задачи с владельцем, сроком, приоритетом и прогрессом.
Coordination-артефакт: НЕ выполняется автоматически (статусы меняет владелец/AI-совет).

БЕЗОПАСНОСТЬ:
- задача — только координация/план; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ExecutionTask(Base, TimestampMixin):
    """Задача исполнения (per-objective, без секретов)."""

    __tablename__ = "execution_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    objective_id: Mapped[int] = mapped_column(
        ForeignKey("execution_objectives.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # pending | assigned | in_progress | blocked | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # `metadata` зарезервировано SQLAlchemy → task_metadata (в API отдаётся как "metadata").
    task_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
