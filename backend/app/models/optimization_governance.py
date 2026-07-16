"""Governance-запись оптимизации (v0.8.2) — управление портфелем улучшений.

Ведёт жизненный цикл улучшения на уровне портфеля: статус governance, статус approval, приоритет,
владелец, заметки ревью. Только управление (review/approve/reject/ownership) — улучшение НЕ
применяется и эксперименты НЕ запускаются автоматически.

БЕЗОПАСНОСТЬ:
- governance — только управление статусами/владельцами; НЕ меняет бизнес/KPI; секретов нет.
"""

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Статус governance-записи (жизненный цикл в портфеле).
GOVERNANCE_STATUSES: tuple[str, ...] = (
    "identified",
    "review",
    "approved",
    "rejected",
    "active",
    "completed",
    "archived",
)
# Статус согласования.
APPROVAL_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")
# Статус влияния (impact).
IMPACT_STATUSES: tuple[str, ...] = ("unknown", "measuring", "positive", "neutral", "negative")
# Приоритет.
PRIORITIES: tuple[str, ...] = ("critical", "high", "medium", "low")


class OptimizationGovernance(Base, TimestampMixin):
    """Portfolio-governance улучшения (per-project, без секретов)."""

    __tablename__ = "optimization_governances"
    __table_args__ = (Index("ix_optimization_governances_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    optimization_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # identified | review | approved | rejected | active | completed | archived
    status: Mapped[str] = mapped_column(String(20), default="identified", nullable=False)
    # pending | approved | rejected
    approval_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    review_notes: Mapped[str | None] = mapped_column(Text, default=None)
