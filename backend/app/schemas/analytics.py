"""Pydantic-схемы аналитики публикаций (Этап 8)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PostAnalyticsSnapshotBase(BaseModel):
    """Общие метрики снимка (вводимые пользователем/провайдером)."""

    impressions: int = 0
    reach: int = 0
    views: int = 0
    likes: int = 0
    reactions: int = 0
    comments: int = 0
    shares: int = 0
    saves: int = 0
    clicks: int = 0
    raw_metrics: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"


class PostAnalyticsSnapshotCreate(PostAnalyticsSnapshotBase):
    """Данные для ручного создания снимка (через API)."""

    post_id: int
    post_publication_id: int | None = None
    platform: str = "manual"
    snapshot_at: datetime | None = None


class PostAnalyticsSnapshotInsert(PostAnalyticsSnapshotBase):
    """Полный набор колонок снимка (внутренний — после расчёта метрик)."""

    post_id: int
    post_publication_id: int | None = None
    project_id: int
    topic_id: int | None = None
    platform: str
    snapshot_at: datetime
    ctr: float = 0.0
    engagement_rate: float = 0.0


class PostAnalyticsSnapshotUpdate(BaseModel):
    """Частичное обновление снимка (ручная правка метрик)."""

    impressions: int | None = None
    reach: int | None = None
    views: int | None = None
    likes: int | None = None
    reactions: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    ctr: float | None = None
    engagement_rate: float | None = None
    raw_metrics: dict[str, Any] | None = None
    source: str | None = None
    platform: str | None = None
    snapshot_at: datetime | None = None


class PostAnalyticsSnapshotRead(PostAnalyticsSnapshotBase):
    """Представление снимка в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    post_id: int
    post_publication_id: int | None = None
    project_id: int
    topic_id: int | None = None
    platform: str
    snapshot_at: datetime
    ctr: float
    engagement_rate: float
    created_at: datetime
    updated_at: datetime


class PostAnalyticsIngestRequest(BaseModel):
    """Запрос на загрузку метрик по публикации."""

    metrics: dict[str, int] | None = None
    source: str = "manual"
    snapshot_at: datetime | None = None


class PostAnalyticsIngestResult(BaseModel):
    """Результат загрузки метрик (созданный снимок)."""

    post_id: int
    post_publication_id: int | None = None
    snapshot: PostAnalyticsSnapshotRead


class PostPerformanceReport(BaseModel):
    """Агрегированная эффективность одного поста по всем снимкам."""

    post_id: int
    project_id: int
    topic_id: int | None = None
    title: str | None = None
    status: str
    total_impressions: int = 0
    total_reach: int = 0
    total_views: int = 0
    total_engagements: int = 0
    total_clicks: int = 0
    avg_ctr: float = 0.0
    avg_engagement_rate: float = 0.0
    snapshots_count: int = 0
    platforms: dict[str, Any] = Field(default_factory=dict)


class TopicPerformanceItem(BaseModel):
    """Эффективность одной темы."""

    topic_id: int
    topic_title: str
    cluster: str | None = None
    posts_count: int = 0
    snapshots_count: int = 0
    total_impressions: int = 0
    total_reach: int = 0
    total_engagements: int = 0
    total_clicks: int = 0
    avg_ctr: float = 0.0
    avg_engagement_rate: float = 0.0
    performance_score: float = 0.0


class TopicPerformanceReport(BaseModel):
    """Отчёт эффективности тем проекта (отсортирован по score)."""

    project_id: int
    project_slug: str
    items: list[TopicPerformanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ClusterPerformanceItem(BaseModel):
    """Эффективность одного кластера."""

    cluster: str
    topics_count: int = 0
    posts_count: int = 0
    total_impressions: int = 0
    total_engagements: int = 0
    total_clicks: int = 0
    avg_ctr: float = 0.0
    avg_engagement_rate: float = 0.0
    performance_score: float = 0.0


class ClusterPerformanceReport(BaseModel):
    """Отчёт эффективности кластеров проекта (отсортирован по score)."""

    project_id: int
    project_slug: str
    items: list[ClusterPerformanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProjectAnalyticsSummary(BaseModel):
    """Сводная аналитика проекта."""

    project_id: int
    project_slug: str
    posts_count: int = 0
    published_posts_count: int = 0
    snapshots_count: int = 0
    total_impressions: int = 0
    total_reach: int = 0
    total_engagements: int = 0
    total_clicks: int = 0
    avg_ctr: float = 0.0
    avg_engagement_rate: float = 0.0
    top_topics: list[TopicPerformanceItem] = Field(default_factory=list)
    top_clusters: list[ClusterPerformanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalyticsFeedbackSignal(BaseModel):
    """Сигнал обратной связи для будущей приоритизации тем."""

    cluster: str
    topic_id: int | None = None
    signal_type: str
    value: float
    reason: str


class AnalyticsFeedbackReport(BaseModel):
    """Набор feedback-сигналов по проекту."""

    project_id: int
    project_slug: str
    signals: list[AnalyticsFeedbackSignal] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
