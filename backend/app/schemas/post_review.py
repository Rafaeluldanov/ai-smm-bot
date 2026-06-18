"""Pydantic-схемы для согласования постов (Этап 6)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PostReviewActionBase(BaseModel):
    """Общие поля действия согласования."""

    post_id: int
    action: str
    from_status: str | None = None
    to_status: str | None = None
    comment: str | None = None
    actor_name: str | None = None
    actor_role: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class PostReviewActionCreate(PostReviewActionBase):
    """Данные для создания записи журнала согласования."""


class PostReviewActionRead(PostReviewActionBase):
    """Представление действия согласования в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class PostReviewDecisionRequest(BaseModel):
    """Запрос на решение по посту (submit/approve/reject/...)."""

    comment: str | None = None
    actor_name: str | None = None
    actor_role: str | None = "manager"


class PostReviewEditRequest(BaseModel):
    """Запрос на ручную правку поста перед согласованием."""

    title: str | None = None
    telegram_text: str | None = None
    vk_text: str | None = None
    instagram_text: str | None = None
    hashtags: list[str] | None = None
    seo_keywords: list[str] | None = None
    media_asset_id: int | None = None
    comment: str | None = None
    actor_name: str | None = None
    actor_role: str | None = "manager"


class PostReviewCommentRequest(BaseModel):
    """Запрос на добавление комментария (без смены статуса)."""

    comment: str
    actor_name: str | None = None
    actor_role: str | None = "manager"


class PostReviewTimeline(BaseModel):
    """История действий согласования по посту."""

    post_id: int
    current_status: str
    actions: list[PostReviewActionRead] = Field(default_factory=list)


class PostReviewCard(BaseModel):
    """Карточка поста для согласования (сводка + предупреждения)."""

    post_id: int
    project_id: int
    topic_id: int | None = None
    media_asset_id: int | None = None
    title: str | None = None
    status: str
    telegram_text: str | None = None
    vk_text: str | None = None
    instagram_text: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    seo_keywords: list[str] = Field(default_factory=list)
    review_actions_count: int
    last_action_at: datetime | None = None
    warnings: list[str] = Field(default_factory=list)
