"""Задача владельца (v0.7.1) — единица AI Chief of Staff (Suggest → Accept → Complete).

AI-ассистент выделяет из брифинга приоритетные задачи для владельца (усилить CTA,
пересмотреть слабые темы, повторить работающую кампанию) с приоритетом, обоснованием и
ожидаемым эффектом.

БЕЗОПАСНОСТЬ:
- задача НЕ выполняется автоматически — ассистент лишь предлагает и фиксирует статус;
  accept/complete НЕ запускают внешних действий (CRM/бюджет/реклама/публикации/live). Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AIBusinessTask(Base, TimestampMixin):
    """Одна задача владельца, предложенная AI-ассистентом (per-project, без секретов)."""

    __tablename__ = "ai_business_tasks"
    __table_args__ = (
        Index("ix_ai_business_tasks_project_status", "project_id", "status"),
        Index("ix_ai_business_tasks_briefing", "briefing_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    briefing_id: Mapped[int | None] = mapped_column(
        ForeignKey("executive_briefings.id", ondelete="SET NULL"), default=None
    )
    # growth | revenue | conversion | content | sales | efficiency | campaign
    task_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # critical | high | medium | low  (числовой score — в priority_score)
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # suggested | accepted | rejected | completed
    status: Mapped[str] = mapped_column(String(20), default="suggested", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    source_modules: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    accepted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
