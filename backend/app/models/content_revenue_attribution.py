"""Атрибуция выручки на контент (v0.6.8) — «какая публикация принесла деньги».

Строка атрибуции связывает выручку (из ``AILeadEvent``) с постом/кампанией по выбранной
модели (first_touch / last_touch / multi_touch). Слой аналитический: ничего не отправляет
и не меняет; хранит только агрегаты и обоснование.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ContentRevenueAttribution(Base, TimestampMixin):
    """Одна строка атрибуции выручки на контент (без секретов)."""

    __tablename__ = "content_revenue_attributions"
    __table_args__ = (
        Index("ix_content_revenue_attr_project_model", "project_id", "attribution_model"),
        Index("ix_content_revenue_attr_post", "post_id"),
        Index("ix_content_revenue_attr_campaign", "campaign_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), default=None
    )
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_campaigns.id", ondelete="SET NULL"), default=None
    )
    lead_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_lead_events.id", ondelete="SET NULL"), default=None
    )
    # first_touch | last_touch | multi_touch
    attribution_model: Mapped[str] = mapped_column(String(20), nullable=False)
    revenue_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
