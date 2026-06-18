"""Pydantic-схемы для Topic и контент-плана."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TopicBase(BaseModel):
    """Общие поля темы."""

    project_id: int
    title: str
    cluster: str | None = None
    priority_score: float = 0.0
    business_priority: int = 0
    seo_keywords: list[str] = Field(default_factory=list)
    status: str = "candidate"


class TopicCreate(TopicBase):
    """Данные для создания темы."""


class TopicUpdate(BaseModel):
    """Данные для частичного обновления темы (все поля опциональны)."""

    title: str | None = None
    cluster: str | None = None
    priority_score: float | None = None
    business_priority: int | None = None
    seo_keywords: list[str] | None = None
    status: str | None = None


class TopicRead(TopicBase):
    """Представление темы в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class TopicStatusUpdate(BaseModel):
    """Запрос на смену статуса темы."""

    status: str


class TopicCandidateRead(BaseModel):
    """Тема-кандидат с рассчитанными сигналами и объяснением выбора."""

    title: str
    cluster: str
    priority_score: float
    business_priority: int
    media_readiness_score: float
    search_demand_score: float
    commercial_intent_score: float
    seasonality_score: float
    trend_score: float
    competition_score: float
    seo_keywords: list[str] = Field(default_factory=list)
    recommended_formats: list[str] = Field(default_factory=list)
    related_media_tags: list[str] = Field(default_factory=list)
    explanation: str
    status: str = "recommended"


class TopicSelectionRequest(BaseModel):
    """Параметры выбора тем."""

    business_priorities: dict[str, int] | None = None
    weeks: int = 1
    posts_per_week: int = 3
    include_low_media_readiness: bool = False


class TopicSelectionResult(BaseModel):
    """Результат выбора тем для проекта."""

    project_id: int
    project_slug: str
    selected_count: int
    candidates_count: int
    created: int
    updated: int
    topics: list[TopicCandidateRead] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ContentPlanItem(BaseModel):
    """Один слот недельного контент-плана (тема, а не готовый пост)."""

    week_number: int
    slot_number: int
    suggested_day: str
    topic_title: str
    cluster: str
    recommended_format: str
    priority_score: float
    seo_keywords: list[str] = Field(default_factory=list)
    media_tags: list[str] = Field(default_factory=list)
    explanation: str
    needs_media: bool
    suggested_media_query: str | None = None


class WeeklyContentPlan(BaseModel):
    """Недельный контент-план проекта."""

    project_id: int
    project_slug: str
    weeks: int
    posts_per_week: int
    items: list[ContentPlanItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
