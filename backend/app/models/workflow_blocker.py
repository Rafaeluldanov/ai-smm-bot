"""Блокер процесса (v0.7.2) — препятствие в BusinessWorkflow/WorkflowStep.

Блокер фиксирует, что мешает движению процесса (зависимость, ресурс, ожидание одобрения,
нехватка данных, внешний фактор) с тяжестью и статусом. Влияет на health-score процесса.

БЕЗОПАСНОСТЬ:
- блокер — только запись/аналитика; НЕ инициирует внешних действий. Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class WorkflowBlocker(Base, TimestampMixin):
    """Один блокер бизнес-процесса (per-workflow, без секретов)."""

    __tablename__ = "workflow_blockers"
    __table_args__ = (
        Index("ix_workflow_blockers_workflow_status", "workflow_id", "status"),
        Index("ix_workflow_blockers_step", "step_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("business_workflows.id", ondelete="CASCADE"), index=True, nullable=False
    )
    step_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_steps.id", ondelete="SET NULL"), default=None
    )
    # dependency | resource | approval | missing_data | external
    blocker_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # open | resolved
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    resolved_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
