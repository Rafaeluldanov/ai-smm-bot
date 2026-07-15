"""Этап процесса (v0.7.2) — единица BusinessWorkflow (Assign → Track → Complete).

Этап описывает конкретную единицу работы процесса: порядок, ответственный, срок, статус,
прогресс. AI-задача (Chief of Staff) или бизнес-действие (Business OS) может стать этапом.

БЕЗОПАСНОСТЬ:
- этап НЕ выполняется автоматически — assign/complete лишь меняют статус;
  НЕ запускают внешних действий (CRM/бюджет/реклама/публикации/live). Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class WorkflowStep(Base, TimestampMixin):
    """Один этап бизнес-процесса (per-workflow, без секретов)."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        Index("ix_workflow_steps_workflow_order", "workflow_id", "order_number"),
        Index("ix_workflow_steps_workflow_status", "workflow_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("business_workflows.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # pending | assigned | in_progress | blocked | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    deadline: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    progress_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    step_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
