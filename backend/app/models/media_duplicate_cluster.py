"""Модель кластера дублей медиа (duplicate clusters) — v0.4.7.

Botfleet группирует визуально похожие/дублирующиеся медиа в кластеры с canonical-ассетом,
similarity_score, причинами и рекомендованными действиями. Файлы НЕ удаляются на этом этапе.

БЕЗОПАСНОСТЬ:
- ``cluster_metadata``/``reasons`` не содержат секретов и внутренних путей к файлам;
- строго account/project-scoped; авто-удаление/скрытие дублей выключено по умолчанию.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

MEDIA_DUPLICATE_CLUSTER_STATUSES: tuple[str, ...] = (
    "active",
    "reviewed",
    "ignored",
    "resolved",
    "failed",
)
MEDIA_DUPLICATE_ACTIONS: tuple[str, ...] = (
    "keep_canonical",
    "hide_duplicate",
    "retag_duplicate",
    "replace_in_schedule",
    "merge_series",
    "ignore",
    "needs_review",
)


class MediaDuplicateCluster(Base, TimestampMixin):
    """Кластер похожих/дублирующихся медиа (active → reviewed/ignored/resolved). Без удаления."""

    __tablename__ = "media_duplicate_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # active | reviewed | ignored | resolved | failed
    status: Mapped[str] = mapped_column(String(20), index=True, default="active", nullable=False)
    # exact_duplicate | near_duplicate | visually_similar | same_series | ...
    cluster_type: Mapped[str] = mapped_column(
        String(30), index=True, default="unknown", nullable=False
    )

    canonical_media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True, default=None
    )
    member_media_asset_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    member_fingerprint_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    similarity_score: Mapped[float] = mapped_column(Float, index=True, default=0.0, nullable=False)
    reasons: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    recommended_actions: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    reviewed_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    cluster_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
