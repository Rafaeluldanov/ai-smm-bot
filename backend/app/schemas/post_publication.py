"""Pydantic-схемы для публикаций поста (Этап 7)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _default_platforms() -> list[str]:
    return ["telegram", "vk"]


class PostPublicationBase(BaseModel):
    """Общие поля публикации."""

    post_id: int
    project_id: int
    platform: str
    target_id: str | None = None
    status: str = "pending"
    external_post_id: str | None = None
    external_url: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    error_message: str | None = None
    attempts: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)


class PostPublicationCreate(PostPublicationBase):
    """Данные для создания публикации."""


class PostPublicationUpdate(BaseModel):
    """Частичное обновление публикации (все поля опциональны)."""

    target_id: str | None = None
    status: str | None = None
    external_post_id: str | None = None
    external_url: str | None = None
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    error_message: str | None = None
    attempts: int | None = None
    payload: dict[str, Any] | None = None


class PostPublicationRead(PostPublicationBase):
    """Представление публикации в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class PostScheduleRequest(BaseModel):
    """Запрос на планирование публикаций поста."""

    platforms: list[str] = Field(default_factory=_default_platforms)
    scheduled_at: datetime | None = None
    target_ids: dict[str, str] | None = None


class PostPublishRequest(BaseModel):
    """Запрос на публикацию поста сейчас."""

    platforms: list[str] | None = None
    force: bool = False


class PublishDueRequest(BaseModel):
    """Запрос на публикацию всех «созревших» публикаций."""

    now: datetime | None = None


class PostPublishResult(BaseModel):
    """Результат планирования/публикации одного поста."""

    post_id: int
    post_status: str
    publications: list[PostPublicationRead] = Field(default_factory=list)
    published_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DuePublicationsResult(BaseModel):
    """Сводный результат публикации due-постов планировщиком."""

    processed_posts: int = 0
    processed_publications: int = 0
    published_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    warnings: list[str] = Field(default_factory=list)
