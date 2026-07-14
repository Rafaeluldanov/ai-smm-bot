"""Профиль автономной контент-стратегии (v0.6.6) — «мозг» AI Content Strategist.

Слой РЕКОМЕНДАЦИЙ поверх AI Learning Profile (v0.6.5), аналитики, SEO и трендов.
Хранит per-project стратегическую «память»: бизнес-цель, аудитория, позиционирование,
контентные столпы, предпочтения тем/форматов/площадок, стратегию постинга, сезонность.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ — только агрегаты и предпочтения;
- стратегия НЕ включает live, НЕ публикует и НЕ меняет активный календарь сама по себе
  (изменения только через Recommendation → Review → Apply с подтверждением).
"""

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Content Strategist (Часть 1) ---

# Типы стратегических сигналов.
STRATEGY_SIGNAL_TYPES: tuple[str, ...] = (
    "business_goal",
    "learning",
    "analytics",
    "seo",
    "trend",
    "seasonality",
    "competitor",
    "audience",
)
# Типы рекомендаций.
STRATEGY_RECOMMENDATION_TYPES: tuple[str, ...] = (
    "topic",
    "format",
    "schedule",
    "platform",
    "media",
    "cta",
    "campaign",
)
# Статусы рекомендации (Recommendation → Review → Apply).
RECOMMENDATION_STATUSES: tuple[str, ...] = (
    "generated",
    "reviewed",
    "accepted",
    "rejected",
    "applied",
)
# Статусы профиля стратегии.
CONTENT_STRATEGY_PROFILE_STATUSES: tuple[str, ...] = ("learning", "active", "paused")


class ContentStrategyProfile(Base, TimestampMixin):
    """Персональная стратегия контента проекта (одна на проект)."""

    __tablename__ = "content_strategy_profiles"
    __table_args__ = (
        Index("ix_content_strategy_profiles_project", "project_id", unique=True),
        Index("ix_content_strategy_profiles_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # learning | active | paused
    status: Mapped[str] = mapped_column(String(20), default="learning", index=True, nullable=False)
    business_goal: Mapped[str | None] = mapped_column(String(64), default=None)

    target_audience: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    brand_positioning: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    content_pillars: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    avoided_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_formats: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    preferred_platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    posting_strategy: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    seasonality_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    last_strategy_update: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
