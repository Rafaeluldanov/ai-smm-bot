"""Модель временной публичной ссылки на медиа (media-proxy).

Instagram Graph API публикует по публичному HTTPS ``image_url``, а не по локальному
файлу. Botfleet выдаёт временную ссылку ``/media/public/{token}``.

БЕЗОПАСНОСТЬ:
- raw-токен в БД НЕ хранится — только ``token_hash`` (sha256) и короткий ``token_prefix``
  (для показа/поиска). Сам токен показывается пользователю лишь в момент создания ссылки.
- ссылка привязана к account/project/media_asset, ограничена по времени (``expires_at``)
  и может быть отозвана (``status=revoked``).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PublicMediaLink(Base, TimestampMixin):
    """Временная публичная ссылка на медиа-актив проекта (media-proxy)."""

    __tablename__ = "public_media_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
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
    # sha256(token) — raw-токен не хранится; token_prefix — первые символы для показа.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    token_prefix: Mapped[str | None] = mapped_column(String(16), default=None)
    # instagram | preview | external_platform | download | other
    purpose: Mapped[str] = mapped_column(String(30), default="instagram", nullable=False)
    # active | revoked | expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(100), default=None)
    file_name: Mapped[str | None] = mapped_column(String(512), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Прочие несекретные метаданные (source, warnings и т. п.). Токен сюда НЕ пишется.
    link_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
