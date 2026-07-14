"""Модель медиа-актива (фото/видео из хранилища)."""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class MediaAsset(Base, TimestampMixin):
    """Медиафайл, привязанный к проекту.

    Поле ``tags`` хранит структуру, формируемую тегированием, например::

        {
            "products": ["худи"],
            "technologies": ["шелкография"],
            "details": ["карман", "жаккард"],
            "topics": ["худи с логотипом", "корпоративный мерч"]
        }
    """

    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    # Путь файла на Яндекс Диске — бизнес-уникален (anti-duplicate при синхронизации).
    yandex_disk_path: Mapped[str | None] = mapped_column(
        String(1024), default=None, unique=True, index=True
    )

    # Источник: "internal" | "external_stock" | "upload" и т. п.
    source_type: Mapped[str] = mapped_column(
        String(50), default="internal", index=True, nullable=False
    )
    # Тип лицензии: "company_owned" | "external_needs_review" | "commercial_use_required" ...
    license_type: Mapped[str | None] = mapped_column(String(50), default=None)

    title: Mapped[str | None] = mapped_column(String(512), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    tags: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    # Статус: "new" | "approved" | "approved_video" | "needs_license_review" | "used" ...
    status: Mapped[str] = mapped_column(String(50), default="new", index=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # --- Курирование медиатеки (v0.4.8) ---
    # Видимость для авто-подбора: selectable | hidden_duplicate | hidden_weak | hidden_manual |
    # archived | restored. Скрытые НЕ выбираются auto media selection; ФАЙЛ не удаляется.
    selection_visibility: Mapped[str] = mapped_column(
        String(30), default="selectable", index=True, nullable=False
    )
    # Статус курирования медиа: new | reviewed | duplicate | retag_pending | replaced ...
    curation_status: Mapped[str] = mapped_column(String(30), default="new", nullable=False)
    # Заметки курирования (без секретов/путей): причина скрытия, canonical id и т. п.
    curation_notes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    # v0.6.2 media-proxy: генерировалась ли публичная ссылка доставки и когда (последний раз).
    proxy_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_proxy_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
