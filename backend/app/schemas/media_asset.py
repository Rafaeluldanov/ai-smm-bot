"""Pydantic-схемы для MediaAsset."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MediaAssetBase(BaseModel):
    """Общие поля медиа-актива."""

    project_id: int
    file_name: str
    yandex_disk_path: str | None = None
    source_type: str = "internal"
    license_type: str | None = None
    title: str | None = None
    description: str | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    status: str = "new"


class MediaAssetCreate(MediaAssetBase):
    """Данные для создания медиа-актива."""


class MediaAssetUpdate(BaseModel):
    """Данные для частичного обновления медиа-актива (все поля опциональны)."""

    file_name: str | None = None
    yandex_disk_path: str | None = None
    source_type: str | None = None
    license_type: str | None = None
    title: str | None = None
    description: str | None = None
    tags: dict[str, Any] | None = None
    status: str | None = None


class MediaAssetRead(MediaAssetBase):
    """Представление медиа-актива в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    last_used_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MediaAssetSyncResult(BaseModel):
    """Результат синхронизации медиа проекта с Яндекс Диском."""

    project_id: int
    project_slug: str
    scanned_folders: list[str] = Field(default_factory=list)
    found_files: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class MediaAssetStatusUpdate(BaseModel):
    """Запрос на смену статуса медиа-актива."""

    status: str


class MediaAssetAnalysisResult(BaseModel):
    """Результат анализа одного медиа-актива."""

    media_asset_id: int
    project_id: int
    project_slug: str | None = None
    file_name: str
    saved: bool
    tags: dict[str, Any]


class MediaAssetRetagResult(BaseModel):
    """Результат повторного тегирования медиа проекта."""

    project_id: int
    project_slug: str
    processed: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class MediaAssetTagsSummary(BaseModel):
    """Сводка частот тегов по группам (для будущего выбора тем)."""

    project_id: int | None = None
    total_assets: int
    products: dict[str, int] = Field(default_factory=dict)
    technologies: dict[str, int] = Field(default_factory=dict)
    details: dict[str, int] = Field(default_factory=dict)
    materials: dict[str, int] = Field(default_factory=dict)
    colors: dict[str, int] = Field(default_factory=dict)
    categories: dict[str, int] = Field(default_factory=dict)
    use_cases: dict[str, int] = Field(default_factory=dict)
    audiences: dict[str, int] = Field(default_factory=dict)


class ShootingTaskSuggestion(BaseModel):
    """Рекомендация по досъёмке недостающего медиа."""

    project_id: int
    project_slug: str
    missing_tag: str
    tag_group: str
    reason: str
    suggested_folder: str
    suggested_shots: list[str] = Field(default_factory=list)
