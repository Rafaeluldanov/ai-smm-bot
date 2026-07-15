"""Операционный риск (v0.7.3) — единица AI Operations Control Center.

Риск фиксирует проблему, обнаруженную при операционном анализе (задержка процесса,
падение выручки/конверсии, контент-провал, нехватка данных, блок исполнения), с тяжестью,
источником и рекомендованным действием. Влияет на health-score.

БЕЗОПАСНОСТЬ:
- риск — только запись/аналитика; resolve лишь меняет статус, НЕ выполняет действий. Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class OperationsRisk(Base, TimestampMixin):
    """Один операционный риск проекта (per-project, без секретов)."""

    __tablename__ = "operations_risks"
    __table_args__ = (
        Index("ix_operations_risks_project_status", "project_id", "status"),
        Index("ix_operations_risks_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # workflow_delay | revenue_drop | conversion_drop | content_gap | missing_data | execution_block
    risk_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # low | medium | high | critical
    severity: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    # open | resolved
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    # модуль-источник (growth_agent / sales_intelligence / workflow_manager / ...)
    source_module: Mapped[str | None] = mapped_column(String(40), default=None)
    source_entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    recommended_action: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    resolved_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
