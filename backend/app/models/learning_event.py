"""Событие обучения (v0.8.0) — факт обучения из опыта.

Фиксирует событие обучения (успех/провал/отклонение/улучшение/инсайт) с его влиянием.
Append-only.

БЕЗОПАСНОСТЬ:
- событие — аналитика обучения; секретов не содержит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType


class LearningEvent(Base):
    """Событие обучения (per-project, append-only, без секретов)."""

    __tablename__ = "learning_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # success | failure | deviation | improvement | insight
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Опыт-источник (SET NULL — событие переживает удаление опыта).
    experience_id: Mapped[int | None] = mapped_column(
        ForeignKey("experience_memories.id", ondelete="SET NULL"), index=True, default=None
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
