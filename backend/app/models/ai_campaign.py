"""AI-кампания (v0.6.7) — сущность автономного маркетингового кампейн-менеджера.

Botfleet переходит от «создавать хорошие посты» к «управлять кампаниями»: цель +
продукт + аудитория + период + стратегия (этапы/темы/форматы/CTA/KPI). Это слой
ПЛАНИРОВАНИЯ и рекомендаций поверх Content Strategy (v0.6.6) и AI Learning (v0.6.5).

БЕЗОПАСНОСТЬ:
- строго per-project; секретов/токенов НЕТ — только план и агрегаты;
- кампания НЕ публикует, НЕ включает live, НЕ меняет активный календарь сама;
  всё через flow Campaign → Plan → Review → Approve → Calendar Draft (с подтверждением).
"""

from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины AI Campaign Manager (Часть 1) ---

# Цели кампании.
CAMPAIGN_GOALS: tuple[str, ...] = (
    "sales",
    "awareness",
    "launch",
    "engagement",
    "education",
    "recruitment",
)
# Статусы кампании.
CAMPAIGN_STATUSES: tuple[str, ...] = (
    "draft",
    "planning",
    "review",
    "approved",
    "active",
    "completed",
    "paused",
)
# Типы этапов (воронка).
CAMPAIGN_STAGE_TYPES: tuple[str, ...] = (
    "awareness",
    "interest",
    "trust",
    "conversion",
    "retention",
)
# Статусы рекомендации кампании.
CAMPAIGN_RECOMMENDATION_STATUSES: tuple[str, ...] = (
    "generated",
    "accepted",
    "rejected",
    "applied",
)


class AICampaign(Base, TimestampMixin):
    """Маркетинговая AI-кампания проекта."""

    __tablename__ = "ai_campaigns"
    __table_args__ = (
        Index("ix_ai_campaigns_project_status", "project_id", "status"),
        Index("ix_ai_campaigns_account", "account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # sales | awareness | launch | engagement | education | recruitment
    goal: Mapped[str] = mapped_column(String(20), nullable=False)
    # draft | planning | review | approved | active | completed | paused
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    product_context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    audience_context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    business_context: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    start_date: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    end_date: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)

    strategy_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    kpi_targets: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    approved_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
