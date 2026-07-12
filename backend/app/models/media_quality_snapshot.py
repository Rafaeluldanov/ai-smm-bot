"""Модель снимка качества медиа (media quality scoring) — v0.4.6.

Botfleet оценивает каждое медиа проекта: качество/релевантность/свежесть/уникальность/
пригодность к платформе, выявляет проблемы и повторы и сохраняет снимок оценки
(:class:`MediaQualitySnapshot`). Это НЕ этап live-публикаций и НЕ внешний AI.

БЕЗОПАСНОСТЬ:
- ``source_signals``/``snapshot_metadata`` не содержат секретов и внутренних путей к файлам;
- строго account/project-scoped; никаких live-публикаций/внешних вызовов/внешнего AI;
- оценка — правило-ориентированная (без image embeddings на этом этапе).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.6): единые перечисления значений (Part 1 спецификации). --- #
MEDIA_QUALITY_STATUSES: tuple[str, ...] = (
    "pending",
    "scored",
    "needs_tags",
    "weak",
    "good",
    "excellent",
    "duplicate",
    "unsupported",
    "failed",
)
MEDIA_QUALITY_ISSUES: tuple[str, ...] = (
    "too_small",
    "too_large",
    "unsupported_format",
    "heic_conversion_needed",
    "video_not_supported",
    "recently_used",
    "duplicate_candidate",
    "weak_topic_match",
    "missing_tags",
    "missing_product_tags",
    "missing_technology_tags",
    "instagram_public_url_required",
    "media_proxy_not_ready",
    "internal_path_only",
    # v0.4.7: визуальная похожесть (fingerprint/dedup).
    "visually_similar",
    "same_series",
)
MEDIA_QUALITY_SIGNAL_SOURCES: tuple[str, ...] = (
    "metadata",
    "tags",
    "usage_history",
    "metrics",
    "ab_winner",
    "manual_feedback",
    "estimated",
)


class MediaQualitySnapshot(Base, TimestampMixin):
    """Снимок оценки качества одного медиа (pending → scored/weak/good/excellent/duplicate)."""

    __tablename__ = "media_quality_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    media_asset_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_asset_variants.id", ondelete="SET NULL"), default=None
    )
    platform_key: Mapped[str | None] = mapped_column(String(40), index=True, default=None)

    # pending | scored | needs_tags | weak | good | excellent | duplicate | unsupported | failed
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending", nullable=False)

    quality_score: Mapped[int | None] = mapped_column(Integer, default=None)
    relevance_score: Mapped[int | None] = mapped_column(Integer, default=None)
    freshness_score: Mapped[int | None] = mapped_column(Integer, default=None)
    uniqueness_score: Mapped[int | None] = mapped_column(Integer, default=None)
    platform_fit_score: Mapped[int | None] = mapped_column(Integer, default=None)
    overall_score: Mapped[int | None] = mapped_column(Integer, index=True, default=None)

    issue_codes: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    positive_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    negative_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    duplicate_of_media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True, default=None
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    recent_usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    recommended_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommended_actions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    snapshot_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
