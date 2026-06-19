"""Pydantic-схемы для улучшения медиа (Media Enhancement)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MediaAssetVariantBase(BaseModel):
    """Общие поля производного варианта медиа."""

    media_asset_id: int
    project_id: int
    variant_type: str = "enhanced"
    status: str = "created"
    source_media_asset_id: int | None = None
    source_path: str | None = None
    output_path: str | None = None
    output_format: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    operations: list[str] = Field(default_factory=list)
    before_metadata: dict[str, Any] = Field(default_factory=dict)
    after_metadata: dict[str, Any] = Field(default_factory=dict)
    quality_score: float | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None


class MediaAssetVariantCreate(MediaAssetVariantBase):
    """Данные для создания производного варианта."""


class MediaAssetVariantUpdate(BaseModel):
    """Частичное обновление варианта (все поля опциональны)."""

    variant_type: str | None = None
    status: str | None = None
    output_path: str | None = None
    output_format: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    operations: list[str] | None = None
    before_metadata: dict[str, Any] | None = None
    after_metadata: dict[str, Any] | None = None
    quality_score: float | None = None
    warnings: list[str] | None = None
    error_message: str | None = None


class MediaAssetVariantRead(MediaAssetVariantBase):
    """Представление варианта в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class MediaAssetVariantStatusUpdate(BaseModel):
    """Запрос на смену статуса варианта."""

    status: str


class MediaEnhancementRequest(BaseModel):
    """Запрос на улучшение одного медиа-актива.

    ``operations`` позволяет точечно включить/выключить отдельные операции
    профиля (ключи: ``auto_contrast``, ``brightness``, ``white_balance``,
    ``denoise``, ``sharpen``, ``resize``, ``convert``). ``None`` — взять набор
    операций из профиля.
    """

    profile: str = "social_safe"
    force: bool = False
    save: bool = True
    operations: dict[str, bool] | None = None


class MediaEnhancementResult(BaseModel):
    """Результат улучшения одного медиа-актива."""

    media_asset_id: int
    variant: MediaAssetVariantRead | None = None
    status: str
    warnings: list[str] = Field(default_factory=list)
    operations_applied: list[str] = Field(default_factory=list)


class ProjectMediaEnhancementRequest(BaseModel):
    """Запрос на пакетное улучшение медиа проекта."""

    project_id: int | None = None
    project_slug: str | None = None
    status: str | None = "approved"
    limit: int = 100
    profile: str = "social_safe"
    force: bool = False


class ProjectMediaEnhancementResult(BaseModel):
    """Результат пакетного улучшения медиа проекта."""

    project_id: int
    project_slug: str
    profile: str
    total_candidates: int = 0
    enhanced: int = 0
    needs_review: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    results: list[MediaEnhancementResult] = Field(default_factory=list)


class MediaEnhancementSummary(BaseModel):
    """Сводка по производным вариантам (по статусам и типам)."""

    project_id: int | None = None
    total_variants: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_variant_type: dict[str, int] = Field(default_factory=dict)
