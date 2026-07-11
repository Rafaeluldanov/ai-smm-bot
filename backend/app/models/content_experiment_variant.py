"""Модель варианта контент-эксперимента (A/B/C) — v0.4.2.

Каждый вариант — черновик поста (``post_id``), который идёт в очередь ревью и получает
feedback + метрики. Сравнение вариантов выбирает winner.

БЕЗОПАСНОСТЬ: ``variant_metadata`` без секретов; live-публикаций нет.
"""

from typing import Any

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ContentExperimentVariant(Base, TimestampMixin):
    """Один вариант поста в эксперименте (A/B/C)."""

    __tablename__ = "content_experiment_variants"
    __table_args__ = (
        Index("ix_content_experiment_variants_experiment_id", "experiment_id"),
        Index("ix_content_experiment_variants_is_winner", "is_winner"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("content_experiments.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), index=True, default=None
    )
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_publications.id", ondelete="SET NULL"), index=True, default=None
    )
    # A | B | C
    variant_key: Mapped[str] = mapped_column(String(4), nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Угол/стратегия варианта (человекочитаемые ключи).
    angle: Mapped[str | None] = mapped_column(String(64), default=None)
    cta_type: Mapped[str | None] = mapped_column(String(64), default=None)
    text_length_type: Mapped[str | None] = mapped_column(String(32), default=None)
    media_strategy: Mapped[str | None] = mapped_column(String(64), default=None)
    publish_time_strategy: Mapped[str | None] = mapped_column(String(64), default=None)
    # draft | needs_review | approved | rejected | published | measured | winner | loser
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)

    quality_score: Mapped[int | None] = mapped_column(Integer, default=None)
    predicted_engagement_score: Mapped[int | None] = mapped_column(Integer, default=None)
    actual_engagement_score: Mapped[int | None] = mapped_column(Integer, default=None)
    er_percent: Mapped[float | None] = mapped_column(Float, default=None)
    ctr_percent: Mapped[float | None] = mapped_column(Float, default=None)

    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    learning_reasons: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    metrics_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    is_winner: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # higher_er | higher_ctr | client_approved | fewer_edits | better_quality_score |
    # better_conversion_signal | manual_selection
    winner_reason: Mapped[str | None] = mapped_column(String(40), default=None)
    variant_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
