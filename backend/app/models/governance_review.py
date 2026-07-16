"""Ревью governance-записи (v0.8.2) — решение ревьюера.

Фиксирует решение ревьюера по улучшению (approve/reject/needs_changes) с комментарием. Append-only.
Только фиксация решения — ничего не запускает и бизнес не меняет.

БЕЗОПАСНОСТЬ:
- ревью — только запись решения; секретов не содержит.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GovernanceReview(Base):
    """Решение ревью governance-записи (append-only, без секретов)."""

    __tablename__ = "governance_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    governance_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_governances.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    # approve | reject | needs_changes | comment
    decision: Mapped[str] = mapped_column(String(20), default="comment", nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
