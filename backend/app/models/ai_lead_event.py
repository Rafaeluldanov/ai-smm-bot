"""Событие лида/выручки (v0.6.8) — сигнал AI Sales & Lead Intelligence.

Каждый бизнес-сигнал (создан лид / сделка / выигрыш сделки / добавлена выручка),
связанный с публикацией/кампанией/площадкой, фиксируется как ``AILeadEvent``. Поток
событий → attribution (контент → лид → выручка) → Sales Intelligence Profile.

БЕЗОПАСНОСТЬ:
- это АНАЛИТИЧЕСКИЙ слой: НЕ отправляет сообщения клиентам, НЕ меняет CRM, НЕ продаёт,
  НЕ включает live; секретов/токенов не хранит (``event_metadata`` санитизируется).
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Sales & Lead Intelligence (Часть 1) ---

# Источник лида.
LEAD_SOURCE_TYPES: tuple[str, ...] = (
    "post",
    "campaign",
    "platform",
    "referral",
    "manual",
    "crm",
)
# Статус лида.
LEAD_STATUSES: tuple[str, ...] = (
    "new",
    "contacted",
    "qualified",
    "converted",
    "lost",
)
# Тип сигнала выручки.
REVENUE_SIGNAL_TYPES: tuple[str, ...] = (
    "lead_created",
    "deal_created",
    "deal_won",
    "revenue_added",
)
# Модели атрибуции.
ATTRIBUTION_MODELS: tuple[str, ...] = ("first_touch", "last_touch", "multi_touch")


class AILeadEvent(Base, TimestampMixin):
    """Одно событие лида/выручки, связанное с контентом (без секретов)."""

    __tablename__ = "ai_lead_events"
    __table_args__ = (
        Index("ix_ai_lead_events_project_created", "project_id", "created_at"),
        Index("ix_ai_lead_events_project_event", "project_id", "event_type"),
        Index("ix_ai_lead_events_post", "post_id"),
        Index("ix_ai_lead_events_campaign", "campaign_id"),
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
    platform_key: Mapped[str | None] = mapped_column(String(40), default=None)
    # lead_created | deal_created | deal_won | revenue_added
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # new | contacted | qualified | converted | lost
    status: Mapped[str] = mapped_column(String(20), default="new", nullable=False)
    # post | campaign | platform | referral | manual | crm
    source_type: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
