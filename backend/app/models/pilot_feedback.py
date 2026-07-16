"""Обратная связь пилота (v1.0.0) — решение владельца по AI-рекомендации.

Фиксирует, что владелец решил по рекомендации (accepted/rejected/modified) + комментарий и
результат. Только запись обратной связи — НЕ меняет бизнес и НЕ выполняет рекомендацию. Append-only.

БЕЗОПАСНОСТЬ:
- feedback — только запись решения владельца; секретов не содержит; ничего не выполняет.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Решение владельца по рекомендации.
FEEDBACK_DECISIONS: tuple[str, ...] = ("accepted", "rejected", "modified")


class PilotFeedback(Base):
    """Обратная связь по AI-рекомендации (append-only, без секретов)."""

    __tablename__ = "pilot_feedbacks"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("pilot_workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Мягкая ссылка на рекомендацию (без FK — рекомендации формируются на лету).
    recommendation_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # accepted | rejected | modified
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, default=None)
    result: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
