"""Модель fingerprint медиа (visual fingerprinting) — v0.4.7.

Botfleet считает безопасные локальные fingerprint-признаки медиа (file sha256, perceptual/
average/difference hash, color/metadata/tag signature) для поиска визуально похожих и
дублирующихся медиа. Без внешнего AI/vision, без сети по умолчанию, без live-публикаций.

БЕЗОПАСНОСТЬ:
- НЕ хранит raw bytes, внутренние пути к файлам и секреты (только хэши/сигнатуры);
- строго account/project-scoped; никаких внешних вызовов по умолчанию;
- perceptual hash — локально через Pillow; при недоступности байтов → metadata_only fallback.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.4.7): единые перечисления значений (Part 1 спецификации). --- #
MEDIA_FINGERPRINT_STATUSES: tuple[str, ...] = (
    "pending",
    "calculated",
    "partial",
    "unavailable",
    "failed",
)
FINGERPRINT_SOURCES: tuple[str, ...] = (
    "file_bytes",
    "media_variant",
    "yandex_public",
    "metadata_only",
    "tags_only",
    "unavailable",
)
MEDIA_SIMILARITY_TYPES: tuple[str, ...] = (
    "exact_duplicate",
    "near_duplicate",
    "visually_similar",
    "same_series",
    "same_file_name",
    "same_yandex_path",
    "same_tag_signature",
    "heic_jpeg_pair",
    "unknown",
)


class MediaFingerprint(Base, TimestampMixin):
    """Fingerprint одного медиа (pending → calculated/partial/unavailable). Без raw bytes/путей."""

    __tablename__ = "media_fingerprints"

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
        ForeignKey("media_asset_variants.id", ondelete="SET NULL"), index=True, default=None
    )

    # pending | calculated | partial | unavailable | failed
    status: Mapped[str] = mapped_column(String(20), index=True, default="pending", nullable=False)
    # file_bytes | media_variant | yandex_public | metadata_only | tags_only | unavailable
    source: Mapped[str] = mapped_column(String(20), default="unavailable", nullable=False)

    file_sha256: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    perceptual_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    average_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    difference_hash: Mapped[str | None] = mapped_column(String(64), default=None)

    color_signature: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    dimension_signature: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    metadata_signature: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    tag_signature: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    fingerprint_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )

    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
