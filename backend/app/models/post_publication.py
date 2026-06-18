"""Модель публикации поста на платформе (Этап 7).

Одна запись = публикация одного поста на одной платформе (telegram/vk).
Бизнес-уникальность — пара (post_id, platform): один пост не публикуется в одну
и ту же платформу дважды (anti-duplicate / идемпотентность).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class PostPublication(Base, TimestampMixin):
    """Публикация поста на конкретной платформе."""

    __tablename__ = "post_publications"
    __table_args__ = (
        Index("ix_post_publications_post_id_platform", "post_id", "platform", unique=True),
        Index("ix_post_publications_scheduled_at", "scheduled_at"),
        Index("ix_post_publications_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    # Платформа: "telegram" | "vk".
    platform: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Канал/группа назначения (id канала Telegram или owner_id VK).
    target_id: Mapped[str | None] = mapped_column(String(255), default=None)

    # Статус: "pending" | "scheduled" | "publishing" | "published" | "failed" | "skipped".
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True, nullable=False)

    external_post_id: Mapped[str | None] = mapped_column(String(255), default=None)
    external_url: Mapped[str | None] = mapped_column(String(1024), default=None)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Детали публикации: текст, media_asset_id, attachment, raw-ответ клиента и т. п.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
