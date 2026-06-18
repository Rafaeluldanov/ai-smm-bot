"""Модель аналитического снимка публикации поста (Этап 8).

Один снимок = состояние метрик поста на одной платформе в момент ``snapshot_at``.
Снимки накапливаются (audit-like); по ним строятся отчёты и feedback-сигналы.
Реальные API соцсетей здесь не вызываются — данные вводятся вручную или из
fake-провайдера.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PostAnalyticsSnapshot(Base, TimestampMixin):
    """Снимок метрик публикации поста на платформе."""

    __tablename__ = "post_analytics_snapshots"
    __table_args__ = (
        Index("ix_post_analytics_snapshots_snapshot_at", "snapshot_at"),
        Index("ix_post_analytics_snapshots_source", "source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("post_publications.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True, default=None
    )

    # Платформа: "telegram" | "vk" | "manual" | "unknown".
    platform: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    impressions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reach: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    likes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    comments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shares: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saves: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    ctr: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    raw_metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    # Источник: "manual" | "fake_provider" | "telegram_api" | "vk_api".
    source: Mapped[str] = mapped_column(String(30), default="manual", nullable=False)
