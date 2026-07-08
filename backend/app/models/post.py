"""Модель поста для публикации в соцсетях."""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class Post(Base, TimestampMixin):
    """Подготовленный пост с текстами под разные соцсети."""

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True, default=None
    )
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True, default=None
    )

    title: Mapped[str | None] = mapped_column(String(512), default=None)

    telegram_text: Mapped[str | None] = mapped_column(Text, default=None)
    vk_text: Mapped[str | None] = mapped_column(Text, default=None)
    instagram_text: Mapped[str | None] = mapped_column(Text, default=None)

    hashtags: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    seo_keywords: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)

    # Технические заметки генерации (JSON). Для поста с группой медиа хранит
    # media_group_key, media_group_tags, media_asset_ids, media_files, счётчики,
    # флаг selected_for_vk_upload и предупреждения. Для обычного поста — {}.
    generation_notes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    # Статусы Этапа 5: "draft" | "needs_review" | "approved" | "scheduled" |
    # "published" | "rejected" | "needs_media".
    status: Mapped[str] = mapped_column(String(50), default="draft", index=True, nullable=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
