"""Профиль AI Sales Intelligence (v0.6.8) — «память продаж из контента».

Персональная per-project «память»: какие темы/кампании/CTA/площадки приносят лиды и
выручку, паттерны конверсии, инсайты выручки. Аналитический слой поверх Analytics,
AI Learning (v0.6.5) и Campaign Manager (v0.6.7). Секретов не хранит; live не включает.
"""

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# Статусы профиля продаж.
SALES_INTELLIGENCE_PROFILE_STATUSES: tuple[str, ...] = ("learning", "active", "paused")


class SalesIntelligenceProfile(Base, TimestampMixin):
    """Профиль продаж из контента для проекта (одна строка на проект)."""

    __tablename__ = "sales_intelligence_profiles"
    __table_args__ = (
        Index("ix_sales_intelligence_profiles_project", "project_id", unique=True),
        Index("ix_sales_intelligence_profiles_account", "account_id"),
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

    best_lead_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_campaigns: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_cta: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    best_platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    conversion_patterns: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    revenue_insights: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    last_analysis_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
