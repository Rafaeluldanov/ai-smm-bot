"""Исполнительный план AI (v0.7.0) — вывод AI Executive Layer по бизнес-цели.

AIExecutivePlan сводит состояние бизнеса (Growth + Sales + Content + Learning + Analytics)
в исполнительное резюме, приоритетные действия, риски, возможности и ожидаемые исходы.
Это план верхнего уровня; сам он ничего не запускает.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AIExecutivePlan(Base, TimestampMixin):
    """Исполнительный AI-план проекта (по бизнес-цели)."""

    __tablename__ = "ai_executive_plans"
    __table_args__ = (
        Index("ix_ai_executive_plans_project", "project_id"),
        Index("ix_ai_executive_plans_objective", "objective_id"),
        Index("ix_ai_executive_plans_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    objective_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_objectives.id", ondelete="SET NULL"), default=None
    )
    # draft | active | completed | paused (планы читаются по project_id — статус не индексируем)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    executive_summary: Mapped[str | None] = mapped_column(Text, default=None)
    current_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    priority_actions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    opportunities: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_outcomes: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
