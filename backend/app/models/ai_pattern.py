"""AI-паттерн (v0.8.0) — обнаруженная закономерность в опыте бизнеса.

Что работает (success_pattern), что не работает (failure_pattern) и что можно оптимизировать
(optimization_pattern) — с сигналами и уверенностью.

БЕЗОПАСНОСТЬ:
- паттерн — аналитика/наблюдение; секретов не содержит.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AIPattern(Base, TimestampMixin):
    """AI-паттерн в опыте бизнеса (per-project, без секретов)."""

    __tablename__ = "ai_patterns"
    __table_args__ = (Index("ix_ai_patterns_project_type", "project_id", "pattern_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # success_pattern | failure_pattern | optimization_pattern
    pattern_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
