"""Элемент улучшения (v0.8.0) — предложение по улучшению из паттерна.

Backlog улучшений: что изменить, приоритет, ожидаемый эффект, статус жизненного цикла. Только
рекомендация — НЕ применяется автоматически.

БЕЗОПАСНОСТЬ:
- улучшение — только совет; approve/reject меняют лишь статус; секретов не содержит.
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ImprovementItem(Base, TimestampMixin):
    """Элемент backlog улучшений (per-project, без секретов)."""

    __tablename__ = "improvement_items"
    __table_args__ = (Index("ix_improvement_items_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # id паттерна-источника (мягкая ссылка, без FK — избегаем лишних ограничений).
    pattern_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # identified | reviewed | accepted | rejected | completed
    status: Mapped[str] = mapped_column(String(20), default="identified", nullable=False)
    # critical | high | medium | low
    priority: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
