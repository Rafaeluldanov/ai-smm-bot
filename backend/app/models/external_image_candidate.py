"""Модель внешнего изображения-кандидата (Этап 9).

Внешняя картинка (сток/Creative Commons и т. п.) — НЕ наш кейс и не наша работа.
Она может использоваться только как иллюстрация и требует хранения источника,
автора, лицензии и ограничений. Перед использованием в коммерции — review.
Реальные стоки и сеть здесь не задействуются (fake-провайдер).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class ExternalImageCandidate(Base, TimestampMixin):
    """Кандидат внешнего изображения под тему/пост (с лицензией и review)."""

    __tablename__ = "external_image_candidates"
    __table_args__ = (
        Index(
            "ix_external_image_candidates_provider_source_url",
            "provider",
            "source_url",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id", ondelete="SET NULL"), index=True, default=None
    )
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), index=True, default=None
    )

    query: Mapped[str] = mapped_column(String(512), nullable=False)
    # Провайдер: "fake" | "manual" | "unsplash" | "pexels" | "creative_commons".
    provider: Mapped[str] = mapped_column(String(50), index=True, nullable=False)

    source_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    preview_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    download_url: Mapped[str | None] = mapped_column(String(1024), default=None)

    title: Mapped[str | None] = mapped_column(String(512), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)

    author_name: Mapped[str | None] = mapped_column(String(255), default=None)
    author_url: Mapped[str | None] = mapped_column(String(1024), default=None)

    license_name: Mapped[str] = mapped_column(String(100), nullable=False)
    license_url: Mapped[str | None] = mapped_column(String(1024), default=None)

    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    modification_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    attribution_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contains_people: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    contains_logo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    safe_for_business: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    forbidden_usage: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    # Статус review: "candidate" | "needs_review" | "approved" | "rejected" |
    # "converted_to_media_asset".
    review_status: Mapped[str] = mapped_column(
        String(40), default="candidate", index=True, nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), default=None)
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)

    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True, default=None
    )
