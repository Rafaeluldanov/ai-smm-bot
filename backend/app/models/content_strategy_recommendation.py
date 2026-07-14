"""Рекомендация контент-стратегии (v0.6.6) — единица потока Recommendation → Review → Apply.

Каждое стратегическое предложение (больше кейсов / меньше рекламы / другой формат /
расписание / кампания) фиксируется как ``ContentStrategyRecommendation`` со статусом,
обоснованием, уверенностью и ожидаемым эффектом.

БЕЗОПАСНОСТЬ:
- рекомендация НЕ применяется сама по себе — только через ручной ``apply`` с
  подтверждением; секретов/токенов не хранит.
"""

from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ContentStrategyRecommendation(Base, TimestampMixin):
    """Одна стратегическая рекомендация (per-project, без секретов)."""

    __tablename__ = "content_strategy_recommendations"
    __table_args__ = (
        Index("ix_content_strategy_recs_project_status", "project_id", "status"),
        Index("ix_content_strategy_recs_project_type", "project_id", "recommendation_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # topic | format | schedule | platform | media | cta | campaign
    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # generated | reviewed | accepted | rejected | applied
    status: Mapped[str] = mapped_column(String(20), default="generated", index=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    reasoning: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    expected_impact: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # payload применения (что именно менять в content_rules/календаре) — без секретов.
    apply_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    reviewed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), default=None)
