"""Профиль AI-обучения бренда клиента (v0.6.5) — «память» AI Learning Loop.

Клиентоориентированный слой ПОВЕРХ существующего :class:`ClientLearningProfile`
(v0.4.0). Хранит агрегированную, безопасную «память» о том, что работает у
конкретного клиента: темы/форматы/стиль/время/площадки/CTA/медиа. Это НЕ дообучение
модели и НЕ новый генератор — только персональные эвристики per-project.

БЕЗОПАСНОСТЬ / ПРИВАТНОСТЬ:
- строго per-project (account_id + project_id); данные одного клиента НЕ смешиваются;
- секретов/токенов НЕТ — только агрегированные предпочтения и веса;
- обучение НЕ включает live-публикацию и НЕ меняет стратегию само по себе.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Learning Loop (Часть 1) ---

# Типы сигналов обучения.
LEARNING_SIGNAL_TYPES: tuple[str, ...] = (
    "impression",
    "like",
    "comment",
    "share",
    "save",
    "click",
    "lead",
    "conversion",
    "client_rating",
    "manual_feedback",
)
# Типы сущностей, к которым относится сигнал.
LEARNING_ENTITY_TYPES: tuple[str, ...] = (
    "post",
    "topic",
    "format",
    "media",
    "schedule",
    "platform",
)
# Уровни уверенности вывода.
LEARNING_CONFIDENCE_LEVELS: tuple[str, ...] = ("low", "medium", "high")
# Рекомендуемые действия по выводу.
LEARNING_ACTIONS: tuple[str, ...] = ("keep", "increase", "decrease", "avoid", "test")
# Источники сигналов.
LEARNING_SOURCES: tuple[str, ...] = ("analytics", "client", "ai", "system")
# Статусы профиля обучения.
AI_LEARNING_PROFILE_STATUSES: tuple[str, ...] = ("learning", "stable", "paused")


class AILearningProfile(Base, TimestampMixin):
    """Персональная «память» AI Learning Loop для проекта (одна на проект)."""

    __tablename__ = "ai_learning_profiles"
    __table_args__ = (
        Index("ix_ai_learning_profiles_project", "project_id", unique=True),
        Index("ix_ai_learning_profiles_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # learning | stable | paused
    status: Mapped[str] = mapped_column(String(20), default="learning", index=True, nullable=False)

    total_posts_analyzed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_feedback_events: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 0..100 — растёт с числом обработанных сигналов и постов.
    learning_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # --- Обученные предпочтения (JSON, без секретов) ---
    preferred_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    avoided_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_formats: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    avoided_formats: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_styles: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_publish_times: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    content_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    media_preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    cta_preferences: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    last_learning_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
