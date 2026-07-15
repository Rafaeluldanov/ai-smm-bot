"""Executive briefing (v0.7.1) — вход AI Chief of Staff / Executive Assistant Layer.

Персональный AI-ассистент владельца ежедневно/еженедельно анализирует состояние бизнеса
и формирует ``ExecutiveBriefing``: сводку, изменения, риски, возможности и рекомендованные
действия. Это advisory + assistant слой.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ; НЕ выполняет задачи и НЕ меняет
  бизнес/CRM/бюджет/продажи/live — только Analyze → Briefing → Recommend → Approve → Task.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Chief of Staff (Часть 1) ---

# Типы брифинга.
BRIEFING_TYPES: tuple[str, ...] = ("daily", "weekly", "monthly")
# Статусы брифинга.
BRIEFING_STATUSES: tuple[str, ...] = ("generated", "viewed", "archived")
# Приоритеты задачи владельца.
TASK_PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")
# Статусы задачи владельца.
TASK_STATUSES: tuple[str, ...] = ("suggested", "accepted", "rejected", "completed")
# Типы запомненных решений владельца.
DECISION_TYPES: tuple[str, ...] = ("preference", "strategy", "restriction", "approval")


class ExecutiveBriefing(Base, TimestampMixin):
    """Ежедневный/еженедельный брифинг владельца (per-project, без секретов)."""

    __tablename__ = "executive_briefings"
    __table_args__ = (
        Index("ix_executive_briefings_project_type", "project_id", "type"),
        Index("ix_executive_briefings_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # daily | weekly | monthly
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    # generated | viewed | archived
    status: Mapped[str] = mapped_column(String(20), default="generated", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    business_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    key_changes: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    opportunities: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommended_actions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    generated_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    viewed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
