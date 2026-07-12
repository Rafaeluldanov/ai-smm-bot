"""Модель задачи курирования медиатеки (media curation) — v0.4.8.

Botfleet предлагает клиенту задачи по очистке/разметке медиатеки: проверить дубли, выбрать
canonical, подтвердить теги, скрыть дубль, заменить слабое медиа. Теги применяются ТОЛЬКО
после подтверждения клиента; файлы НЕ удаляются; внешнего AI нет.

БЕЗОПАСНОСТЬ:
- ``suggested_*``/``source_signals``/``task_metadata`` не содержат секретов и внутренних путей;
- строго account/project-scoped; авто-применение/скрытие/удаление выключено по умолчанию.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.8): единые перечисления значений (Part 1 спецификации). --- #
MEDIA_CURATION_TASK_TYPES: tuple[str, ...] = (
    "duplicate_review",
    "retag_suggestion",
    "weak_media_review",
    "missing_tags",
    "platform_fit_issue",
    "replace_repeated_media",
    "media_proxy_needed",
    "heic_conversion_needed",
)
MEDIA_CURATION_TASK_STATUSES: tuple[str, ...] = (
    "proposed",
    "accepted",
    "rejected",
    "applied",
    "ignored",
    "restored",
    "expired",
    "failed",
)
MEDIA_CURATION_ACTIONS: tuple[str, ...] = (
    "approve_tags",
    "reject_tags",
    "mark_duplicate",
    "keep_canonical",
    "hide_from_selection",
    "restore_to_selection",
    "ignore_cluster",
    "request_replacement",
    "mark_reviewed",
)
MEDIA_SELECTION_VISIBILITIES: tuple[str, ...] = (
    "selectable",
    "hidden_duplicate",
    "hidden_weak",
    "hidden_manual",
    "archived",
    "restored",
)
# Скрытые для авто-подбора значения видимости (не попадают в auto media selection).
HIDDEN_VISIBILITIES: tuple[str, ...] = (
    "hidden_duplicate",
    "hidden_weak",
    "hidden_manual",
    "archived",
)
TAG_SUGGESTION_SOURCES: tuple[str, ...] = (
    "file_name",
    "existing_tags",
    "duplicate_canonical",
    "crm_category",
    "crm_keywords",
    "product_priorities",
    "technology_priorities",
    "learning_profile",
    "high_performing_tags",
    "manual",
)


class MediaCurationTask(Base, TimestampMixin):
    """Задача курирования медиатеки (proposed → accepted/applied/rejected/ignored). Без удаления."""

    __tablename__ = "media_curation_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, default=None
    )
    media_asset_variant_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_asset_variants.id", ondelete="SET NULL"), default=None
    )
    duplicate_cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_duplicate_clusters.id", ondelete="SET NULL"), index=True, default=None
    )
    quality_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_quality_snapshots.id", ondelete="SET NULL"), index=True, default=None
    )
    fingerprint_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_fingerprints.id", ondelete="SET NULL"), default=None
    )

    task_type: Mapped[str] = mapped_column(
        String(30), index=True, default="retag_suggestion", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), index=True, default="proposed", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    suggested_action: Mapped[str | None] = mapped_column(String(40), default=None)

    suggested_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    suggested_products: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    suggested_technologies: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    affected_media_asset_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    source_signals: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    risk_flags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, index=True, default=0.0, nullable=False)

    applied_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    rejected_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    ignored_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ignored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    idempotency_key: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, default=None
    )
    task_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
