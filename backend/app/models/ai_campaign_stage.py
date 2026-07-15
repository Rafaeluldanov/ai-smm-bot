"""Этап AI-кампании (v0.6.7) — ступень воронки (awareness → … → retention).

Каждый этап несёт свою цель, контентные столпы, рекомендованные форматы/темы и
CTA-стратегию. Этапы генерируются планировщиком кампании; секретов не хранят.
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AICampaignStage(Base, TimestampMixin):
    """Один этап кампании (ступень воронки)."""

    __tablename__ = "ai_campaign_stages"
    __table_args__ = (Index("ix_ai_campaign_stages_campaign", "campaign_id", "order_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("ai_campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # awareness | interest | trust | conversion | retention
    stage_type: Mapped[str] = mapped_column(String(20), nullable=False)
    order_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    goal: Mapped[str | None] = mapped_column(String(64), default=None)

    content_pillars: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommended_formats: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommended_topics: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    cta_strategy: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
