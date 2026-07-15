"""Рекомендация AI-кампании (v0.6.7) — единица потока Review → Accept → Apply.

Каждое предложение по кампании (какие темы/посты/расписание/медиа/CTA) фиксируется как
``AICampaignRecommendation`` со статусом, обоснованием, уверенностью и ожидаемым
результатом. Рекомендация НЕ применяется сама — только через approve+apply кампании.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class AICampaignRecommendation(Base, TimestampMixin):
    """Одна рекомендация в рамках кампании (без секретов)."""

    __tablename__ = "ai_campaign_recommendations"
    __table_args__ = (Index("ix_ai_campaign_recs_campaign_status", "campaign_id", "status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("ai_campaigns.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # topic | post | schedule | media | cta
    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # generated | accepted | rejected | applied
    status: Mapped[str] = mapped_column(String(20), default="generated", index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reviewed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
