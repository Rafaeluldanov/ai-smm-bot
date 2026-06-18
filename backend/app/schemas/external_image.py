"""Pydantic-схемы внешних изображений-кандидатов (Этап 9)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _default_providers() -> list[str]:
    return ["fake"]


class ExternalImageCandidateBase(BaseModel):
    """Общие поля кандидата внешнего изображения."""

    project_id: int
    topic_id: int | None = None
    post_id: int | None = None
    query: str
    provider: str
    source_url: str
    preview_url: str | None = None
    download_url: str | None = None
    title: str | None = None
    description: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    license_name: str
    license_url: str | None = None
    commercial_use_allowed: bool = False
    modification_allowed: bool = False
    attribution_required: bool = False
    contains_people: bool = False
    contains_logo: bool = False
    safe_for_business: bool = False
    forbidden_usage: list[str] = Field(default_factory=list)
    tags: dict[str, Any] = Field(default_factory=dict)
    review_status: str = "candidate"
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None
    media_asset_id: int | None = None


class ExternalImageCandidateCreate(ExternalImageCandidateBase):
    """Данные для создания/upsert кандидата."""


class ExternalImageCandidateUpdate(BaseModel):
    """Частичное обновление кандидата (все поля опциональны)."""

    query: str | None = None
    preview_url: str | None = None
    download_url: str | None = None
    title: str | None = None
    description: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    commercial_use_allowed: bool | None = None
    modification_allowed: bool | None = None
    attribution_required: bool | None = None
    contains_people: bool | None = None
    contains_logo: bool | None = None
    safe_for_business: bool | None = None
    forbidden_usage: list[str] | None = None
    tags: dict[str, Any] | None = None
    review_status: str | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    rejection_reason: str | None = None
    media_asset_id: int | None = None


class ExternalImageCandidateRead(ExternalImageCandidateBase):
    """Представление кандидата в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class ExternalImageSearchRequest(BaseModel):
    """Параметры поиска внешних изображений."""

    project_id: int | None = None
    project_slug: str | None = None
    topic_id: int | None = None
    post_id: int | None = None
    query: str | None = None
    limit: int = 10
    providers: list[str] = Field(default_factory=_default_providers)
    require_commercial_use: bool = True
    require_no_logo: bool = True
    require_safe_for_business: bool = True


class ExternalImageSearchResult(BaseModel):
    """Результат поиска внешних изображений."""

    project_id: int
    project_slug: str
    query: str
    found_count: int = 0
    created: int = 0
    skipped: int = 0
    candidates: list[ExternalImageCandidateRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExternalImageReviewRequest(BaseModel):
    """Запрос на смену статуса review кандидата."""

    review_status: str
    reviewed_by: str | None = None
    rejection_reason: str | None = None


class ExternalImageConvertRequest(BaseModel):
    """Параметры конвертации кандидата в MediaAsset."""

    title: str | None = None
    description: str | None = None
    status: str = "needs_license_review"
    save_to_yandex_disk_path: str | None = None


class ExternalImageConvertResult(BaseModel):
    """Результат конвертации кандидата в MediaAsset."""

    candidate: ExternalImageCandidateRead
    media_asset_id: int
    warnings: list[str] = Field(default_factory=list)


class ExternalImageSafetyReport(BaseModel):
    """Оценка безопасности использования внешнего изображения."""

    candidate_id: int
    can_use_organically: bool
    can_use_in_ads: bool
    can_claim_as_own_case: bool
    required_attribution: str | None = None
    warnings: list[str] = Field(default_factory=list)
    forbidden_usage: list[str] = Field(default_factory=list)
