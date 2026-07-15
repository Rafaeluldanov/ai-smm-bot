"""Бизнес-действие (v0.7.0) — единица исполнительного плана (Review → Accept → Apply).

Каждое приоритетное действие плана (усилить контент / улучшить CTA / запустить черновик
кампании доверия) фиксируется как ``BusinessAction`` с приоритетом, обоснованием,
ожидаемым эффектом и модулями-источниками (Growth/Sales/Content).

БЕЗОПАСНОСТЬ:
- действие НЕ применяется само — только через ручной ``apply`` с подтверждением;
  apply меняет лишь draft-стратегию / draft-кампанию, НЕ live/CRM/деньги. Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class BusinessAction(Base, TimestampMixin):
    """Одно бизнес-действие исполнительного плана (per-project, без секретов)."""

    __tablename__ = "business_actions"
    __table_args__ = (
        Index("ix_business_actions_project_status", "project_id", "status"),
        Index("ix_business_actions_plan", "plan_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_executive_plans.id", ondelete="CASCADE"), default=None
    )
    # growth | revenue | conversion | content | sales | efficiency | campaign
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 0..100 — priority score (impact × confidence × urgency)
    priority: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # generated | accepted | rejected | applied (фильтр по статусу всегда project-scoped —
    # покрыт композитным индексом ix_business_actions_project_status)
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    source_modules: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    # payload применения (что менять в draft-стратегии/кампании) — без секретов.
    apply_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    reviewed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
