"""Pydantic-схемы для Post и генерации постов."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PostBase(BaseModel):
    """Общие поля поста."""

    project_id: int
    topic_id: int | None = None
    media_asset_id: int | None = None
    title: str | None = None
    telegram_text: str | None = None
    vk_text: str | None = None
    instagram_text: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    seo_keywords: list[str] = Field(default_factory=list)
    status: str = "draft"
    scheduled_at: datetime | None = None


class PostCreate(PostBase):
    """Данные для создания поста."""


class PostUpdate(BaseModel):
    """Ручная правка поста (все поля опциональны)."""

    title: str | None = None
    telegram_text: str | None = None
    vk_text: str | None = None
    instagram_text: str | None = None
    hashtags: list[str] | None = None
    seo_keywords: list[str] | None = None
    media_asset_id: int | None = None


class PostStatusUpdate(BaseModel):
    """Запрос на смену статуса поста."""

    status: str


class PostRead(PostBase):
    """Представление поста в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    published_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PostGenerationRequest(BaseModel):
    """Параметры генерации поста по одной теме."""

    topic_id: int | None = None
    topic_title: str | None = None
    recommended_format: str | None = None
    force: bool = False


class PostGenerationResult(BaseModel):
    """Результат генерации поста по теме."""

    post: PostRead
    selected_media_asset_id: int | None = None
    needs_media: bool
    warnings: list[str] = Field(default_factory=list)
    generation_notes: list[str] = Field(default_factory=list)


class WeeklyPostGenerationRequest(BaseModel):
    """Параметры пакетной генерации постов на неделю(и)."""

    project_id: int | None = None
    project_slug: str | None = None
    weeks: int = 1
    posts_per_week: int = 3
    business_priorities: dict[str, int] | None = None


class WeeklyPostGenerationResult(BaseModel):
    """Результат пакетной генерации постов."""

    project_id: int
    project_slug: str
    generated_count: int
    posts: list[PostRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
