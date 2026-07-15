"""Рекомендация роста бизнеса (v0.6.9) — единица потока Review → Accept → Apply.

Каждое advisory-предложение по росту (усилить тему / повторить кампанию / улучшить
конверсию / сфокусироваться на канале) фиксируется как ``BusinessGrowthRecommendation``
со статусом, обоснованием, сигналами-источниками, ожидаемым эффектом и уверенностью.

БЕЗОПАСНОСТЬ:
- рекомендация НЕ применяется сама — только через ручной ``apply`` с подтверждением;
  apply меняет лишь business-профиль / draft-стратегию, НЕ live/publish/CRM. Секретов нет.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class BusinessGrowthRecommendation(Base, TimestampMixin):
    """Одна рекомендация роста бизнеса (per-project, без секретов)."""

    __tablename__ = "business_growth_recommendations"
    __table_args__ = (
        Index("ix_business_growth_recs_project_status", "project_id", "status"),
        Index("ix_business_growth_recs_project_type", "project_id", "recommendation_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # content | campaign | channel | conversion | audience | product | process
    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # generated | reviewed | accepted | rejected | applied
    status: Mapped[str] = mapped_column(String(20), default="generated", index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # payload применения (что менять в business-профиле / draft-стратегии) — без секретов.
    apply_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    reviewed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
