"""Операционная рекомендация (v0.7.3) — единица AI Operations Control Center.

Рекомендация владельцу: что сделать, почему и какой ожидается эффект — генерируется из
рисков и операционных сигналов. Review-only: accept/reject лишь меняют статус.

БЕЗОПАСНОСТЬ:
- рекомендация НЕ исполняется автоматически; accept/reject лишь фиксируют статус,
  НЕ запускают внешних действий (CRM/бюджет/реклама/публикации/live). Секретов нет.
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class OperationsRecommendation(Base, TimestampMixin):
    """Одна операционная рекомендация проекта (per-project, без секретов)."""

    __tablename__ = "operations_recommendations"
    __table_args__ = (
        Index("ix_operations_recommendations_project_status", "project_id", "status"),
        Index("ix_operations_recommendations_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # generated | accepted | rejected
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
