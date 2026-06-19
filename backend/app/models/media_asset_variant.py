"""Модель производной копии медиа-актива (Media Enhancement / Улучшение медиа).

Вариант (``MediaAssetVariant``) — это УЛУЧШЕННАЯ КОПИЯ исходного ``MediaAsset``.
Оригинал НИКОГДА не изменяется и не перезаписывается: улучшение всегда создаёт
новый производный файл и отдельную запись с метаданными обработки.

Поле ``operations`` хранит список применённых операций (например, ``["resize",
"auto_contrast", "sharpen"]``); ``before_metadata`` / ``after_metadata`` — снимок
параметров изображения до и после обработки; ``warnings`` — предупреждения,
из-за которых правка может потребовать ручного review.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class MediaAssetVariant(Base, TimestampMixin):
    """Производный (улучшенный) вариант медиа-актива.

    Тип варианта (``variant_type``):
        - ``enhanced``          — безопасно улучшенная копия для публикаций;
        - ``social_preview``    — превью под соцсети;
        - ``retouch_candidate`` — кандидат на «умную» ретушь (AI пока не подключён).

    Статус (``status``):
        - ``created``      — успешно создан, спорных правок нет;
        - ``needs_review`` — есть предупреждения/спорные правки, нужен просмотр;
        - ``approved``     — проверен и одобрен человеком;
        - ``rejected``     — отклонён;
        - ``failed``       — обработка не удалась (см. ``error_message``).
    """

    __tablename__ = "media_asset_variants"

    id: Mapped[int] = mapped_column(primary_key=True)
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    variant_type: Mapped[str] = mapped_column(
        String(50), default="enhanced", index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(40), default="created", index=True, nullable=False)

    # Исходный медиа-актив/файл (для трассировки происхождения копии).
    source_media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), default=None
    )
    source_path: Mapped[str | None] = mapped_column(String(1024), default=None)

    # Результат обработки (локальный производный файл).
    output_path: Mapped[str | None] = mapped_column(String(1024), default=None)
    output_format: Mapped[str | None] = mapped_column(String(20), default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    file_size: Mapped[int | None] = mapped_column(Integer, default=None)

    operations: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    before_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    after_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, default=None)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
