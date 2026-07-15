"""Профиль роста бизнеса (v0.6.9) — «мозг» AI Business Growth Agent.

Advisory-слой бизнес-аналитики поверх Sales Intelligence (v0.6.8), Content Strategy
(v0.6.6), AI Learning (v0.6.5), Campaign Manager (v0.6.7) и аналитики. Сводит контент +
кампании + лиды + выручку + обучение в Growth Intelligence: состояние бизнеса, сильные/
слабые стороны, возможности, риски и growth_score.

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ — только агрегаты и оценки;
- НЕ меняет бизнес/CRM/бюджет/live/публикации; изменения только через
  Analyze → Recommend → Review → Apply (с подтверждением).
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Business Growth Agent (Часть 1) ---

# Типы сигналов роста.
GROWTH_SIGNAL_TYPES: tuple[str, ...] = (
    "revenue",
    "conversion",
    "content",
    "campaign",
    "audience",
    "platform",
    "efficiency",
    "opportunity",
)
# Типы рекомендаций роста.
GROWTH_RECOMMENDATION_TYPES: tuple[str, ...] = (
    "content",
    "campaign",
    "channel",
    "conversion",
    "audience",
    "product",
    "process",
)
# Статусы рекомендации (Analyze → Recommend → Review → Apply).
GROWTH_RECOMMENDATION_STATUSES: tuple[str, ...] = (
    "generated",
    "reviewed",
    "accepted",
    "rejected",
    "applied",
)
# Статусы профиля роста.
BUSINESS_GROWTH_PROFILE_STATUSES: tuple[str, ...] = ("learning", "active", "paused")


class BusinessGrowthProfile(Base, TimestampMixin):
    """Профиль роста бизнеса проекта (одна строка на проект)."""

    __tablename__ = "business_growth_profiles"
    __table_args__ = (
        Index("ix_business_growth_profiles_project", "project_id", unique=True),
        Index("ix_business_growth_profiles_account", "account_id"),
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

    business_goal: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    growth_targets: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    current_state: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    strengths: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    weaknesses: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    opportunities: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risks: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    growth_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_analysis_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
