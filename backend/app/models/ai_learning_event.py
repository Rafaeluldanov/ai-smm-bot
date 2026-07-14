"""Событие AI Learning Loop (v0.6.5) — единичный сигнал обучения.

Каждый сигнал (метрика аналитики, оценка клиента, ручной фидбэк, системное событие
жизненного цикла поста) фиксируется как ``AILearningEvent``. Поток событий
агрегируется в :class:`AILearningProfile`.

БЕЗОПАСНОСТЬ:
- секретов/токенов НЕ хранит; ``event_metadata`` санитизируется на уровне сервиса;
- полный текст поста НЕ хранится — только идентификаторы и агрегированные значения;
- события НЕ удаляются (reset профиля не трогает историю сигналов).
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AILearningEvent(Base, TimestampMixin):
    """Одно событие/сигнал AI Learning Loop (per-project, без секретов)."""

    __tablename__ = "ai_learning_events"
    __table_args__ = (
        Index("ix_ai_learning_events_project_created", "project_id", "created_at"),
        Index("ix_ai_learning_events_project_entity", "project_id", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # post | topic | format | media | schedule | platform
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, default=None)
    # impression | like | comment | share | save | click | lead | conversion |
    # client_rating | manual_feedback
    event_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # analytics | client | ai | system
    source: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
