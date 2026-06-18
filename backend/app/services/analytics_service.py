"""Сервис аналитики публикаций (Этап 8).

Хранит снимки метрик, считает CTR/engagement_rate/performance_score и строит
отчёты по постам, темам, кластерам и проекту, а также feedback-сигналы для
будущей приоритизации тем. Реальные API соцсетей не вызываются — метрики
вводятся вручную или берутся у fake-провайдера.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.post import Post
from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import (
    analytics_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    topic_repository,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.analytics import (
    AnalyticsFeedbackReport,
    AnalyticsFeedbackSignal,
    ClusterPerformanceItem,
    ClusterPerformanceReport,
    PostAnalyticsSnapshotCreate,
    PostAnalyticsSnapshotInsert,
    PostAnalyticsSnapshotRead,
    PostPerformanceReport,
    ProjectAnalyticsSummary,
    TopicPerformanceItem,
    TopicPerformanceReport,
)
from app.services.analytics_metrics import (
    calculate_ctr,
    calculate_engagement_rate,
    calculate_engagements,
    calculate_performance_score,
)
from app.services.analytics_provider import AnalyticsProviderError, BaseAnalyticsProvider
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

# Пороги для feedback-сигналов.
_BOOST_SCORE = 60.0
_LOW_ENGAGEMENT_RATE = 0.02
_LOW_CTR = 0.01
_MIN_IMPRESSIONS_FOR_CTA = 1000


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _avg(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


class PublicationNotFoundError(Exception):
    """Публикация не найдена (API → 404)."""

    def __init__(self, publication_id: int) -> None:
        self.publication_id = publication_id
        super().__init__(f"Публикация id={publication_id} не найдена")


class AnalyticsInputError(Exception):
    """Некорректный или недостаточный ввод метрик (API → 422)."""


class AnalyticsService:
    """Хранение снимков, расчёт метрик и отчётов, feedback-сигналы."""

    def __init__(self, provider: BaseAnalyticsProvider | None = None) -> None:
        self._provider = provider

    # --- Загрузка снимков ---

    def ingest_snapshot(
        self, db: Session, request: PostAnalyticsSnapshotCreate
    ) -> PostAnalyticsSnapshotRead:
        """Создать снимок из ручного ввода метрик (с расчётом CTR/ER)."""
        post = post_repository.get_post_by_id(db, request.post_id)
        if post is None:
            raise PostNotFoundError(request.post_id)
        metrics = {
            "impressions": request.impressions,
            "reach": request.reach,
            "views": request.views,
            "likes": request.likes,
            "reactions": request.reactions,
            "comments": request.comments,
            "shares": request.shares,
            "saves": request.saves,
            "clicks": request.clicks,
        }
        raw = request.raw_metrics or dict(metrics)
        snapshot = self._store(
            db,
            post=post,
            post_publication_id=request.post_publication_id,
            platform=request.platform,
            source=request.source,
            snapshot_at=request.snapshot_at,
            metrics=metrics,
            raw_metrics=raw,
        )
        return PostAnalyticsSnapshotRead.model_validate(snapshot)

    def ingest_for_publication(
        self,
        db: Session,
        post_publication_id: int,
        source: str = "manual",
        metrics: dict[str, int] | None = None,
    ) -> PostAnalyticsSnapshotRead:
        """Создать снимок по публикации из переданных метрик.

        Метрики обязательны: без них поднимается ``AnalyticsInputError`` (для
        автоматического получения используйте ``fetch_and_store_for_publication``).
        """
        publication = post_publication_repository.get_publication_by_id(db, post_publication_id)
        if publication is None:
            raise PublicationNotFoundError(post_publication_id)
        post = post_repository.get_post_by_id(db, publication.post_id)
        if post is None:
            raise PostNotFoundError(publication.post_id)
        if metrics is None:
            raise AnalyticsInputError(
                "Не переданы метрики (metrics обязателен для ручной загрузки)"
            )

        snapshot = self._store(
            db,
            post=post,
            post_publication_id=publication.id,
            platform=publication.platform,
            source=source,
            snapshot_at=None,
            metrics=metrics,
            raw_metrics=dict(metrics),
        )
        return PostAnalyticsSnapshotRead.model_validate(snapshot)

    def fetch_and_store_for_publication(
        self, db: Session, post_publication_id: int
    ) -> PostAnalyticsSnapshotRead:
        """Получить метрики у провайдера (fake) и сохранить снимок."""
        if self._provider is None:
            raise AnalyticsProviderError("Провайдер аналитики не настроен")
        publication = post_publication_repository.get_publication_by_id(db, post_publication_id)
        if publication is None:
            raise PublicationNotFoundError(post_publication_id)
        post = post_repository.get_post_by_id(db, publication.post_id)
        if post is None:
            raise PostNotFoundError(publication.post_id)

        metrics = self._provider.fetch_post_metrics(publication)
        snapshot = self._store(
            db,
            post=post,
            post_publication_id=publication.id,
            platform=publication.platform,
            source="fake_provider",
            snapshot_at=None,
            metrics=metrics,
            raw_metrics=dict(metrics),
        )
        return PostAnalyticsSnapshotRead.model_validate(snapshot)

    # --- Отчёты ---

    def get_post_performance(self, db: Session, post_id: int) -> PostPerformanceReport:
        """Агрегировать все снимки поста (итоги + разбивка по платформам)."""
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)
        snapshots = analytics_repository.list_snapshots(db, post_id=post_id, limit=10000)
        agg = self._aggregate(snapshots)

        platforms: dict[str, Any] = {}
        for platform in sorted({s.platform for s in snapshots}):
            platform_snaps = [s for s in snapshots if s.platform == platform]
            platform_agg = self._aggregate(platform_snaps)
            platforms[platform] = {
                "snapshots_count": len(platform_snaps),
                "total_impressions": platform_agg["impressions"],
                "total_reach": platform_agg["reach"],
                "total_engagements": platform_agg["engagements"],
                "total_clicks": platform_agg["clicks"],
                "avg_ctr": platform_agg["avg_ctr"],
                "avg_engagement_rate": platform_agg["avg_engagement_rate"],
            }

        return PostPerformanceReport(
            post_id=post.id,
            project_id=post.project_id,
            topic_id=post.topic_id,
            title=post.title,
            status=post.status,
            total_impressions=agg["impressions"],
            total_reach=agg["reach"],
            total_views=agg["views"],
            total_engagements=agg["engagements"],
            total_clicks=agg["clicks"],
            avg_ctr=agg["avg_ctr"],
            avg_engagement_rate=agg["avg_engagement_rate"],
            snapshots_count=len(snapshots),
            platforms=platforms,
        )

    def get_topic_performance(self, db: Session, project_id: int) -> TopicPerformanceReport:
        """Эффективность тем проекта (сгруппировано по topic_id, score desc)."""
        project = self._require_project(db, project_id)
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        topics = {
            topic.id: topic
            for topic in topic_repository.list_topics(db, project_id=project_id, limit=10000)
        }

        warnings: list[str] = []
        if not snapshots:
            warnings.append("Нет снимков аналитики для проекта")

        by_topic: dict[int, list[PostAnalyticsSnapshot]] = {}
        for snapshot in snapshots:
            if snapshot.topic_id is None:
                continue
            by_topic.setdefault(snapshot.topic_id, []).append(snapshot)

        items: list[TopicPerformanceItem] = []
        for topic_id, topic_snaps in by_topic.items():
            topic = topics.get(topic_id)
            agg = self._aggregate(topic_snaps)
            items.append(
                TopicPerformanceItem(
                    topic_id=topic_id,
                    topic_title=topic.title if topic is not None else f"тема #{topic_id}",
                    cluster=topic.cluster if topic is not None else None,
                    posts_count=len({s.post_id for s in topic_snaps}),
                    snapshots_count=len(topic_snaps),
                    total_impressions=agg["impressions"],
                    total_reach=agg["reach"],
                    total_engagements=agg["engagements"],
                    total_clicks=agg["clicks"],
                    avg_ctr=agg["avg_ctr"],
                    avg_engagement_rate=agg["avg_engagement_rate"],
                    performance_score=self._score(agg),
                )
            )

        items.sort(key=lambda item: item.performance_score, reverse=True)
        return TopicPerformanceReport(
            project_id=project.id, project_slug=project.slug, items=items, warnings=warnings
        )

    def get_cluster_performance(self, db: Session, project_id: int) -> ClusterPerformanceReport:
        """Эффективность кластеров проекта (сгруппировано по cluster, score desc)."""
        project = self._require_project(db, project_id)
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        topics = {
            topic.id: topic
            for topic in topic_repository.list_topics(db, project_id=project_id, limit=10000)
        }

        warnings: list[str] = []
        if not snapshots:
            warnings.append("Нет снимков аналитики для проекта")

        by_cluster: dict[str, list[PostAnalyticsSnapshot]] = {}
        topics_by_cluster: dict[str, set[int]] = {}
        for snapshot in snapshots:
            if snapshot.topic_id is None:
                continue
            topic = topics.get(snapshot.topic_id)
            cluster = topic.cluster if topic is not None and topic.cluster else "без кластера"
            by_cluster.setdefault(cluster, []).append(snapshot)
            topics_by_cluster.setdefault(cluster, set()).add(snapshot.topic_id)

        items: list[ClusterPerformanceItem] = []
        for cluster, cluster_snaps in by_cluster.items():
            agg = self._aggregate(cluster_snaps)
            items.append(
                ClusterPerformanceItem(
                    cluster=cluster,
                    topics_count=len(topics_by_cluster[cluster]),
                    posts_count=len({s.post_id for s in cluster_snaps}),
                    total_impressions=agg["impressions"],
                    total_engagements=agg["engagements"],
                    total_clicks=agg["clicks"],
                    avg_ctr=agg["avg_ctr"],
                    avg_engagement_rate=agg["avg_engagement_rate"],
                    performance_score=self._score(agg),
                )
            )

        items.sort(key=lambda item: item.performance_score, reverse=True)
        return ClusterPerformanceReport(
            project_id=project.id, project_slug=project.slug, items=items, warnings=warnings
        )

    def get_project_summary(self, db: Session, project_id: int) -> ProjectAnalyticsSummary:
        """Сводка проекта: итоги + топ тем и кластеров."""
        project = self._require_project(db, project_id)
        posts = post_repository.list_posts(db, project_id=project_id, limit=10000)
        published = [post for post in posts if post.status == "published"]
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        agg = self._aggregate(snapshots)

        topic_report = self.get_topic_performance(db, project_id)
        cluster_report = self.get_cluster_performance(db, project_id)

        warnings: list[str] = []
        if not snapshots:
            warnings.append("Нет снимков аналитики для проекта")

        return ProjectAnalyticsSummary(
            project_id=project.id,
            project_slug=project.slug,
            posts_count=len(posts),
            published_posts_count=len(published),
            snapshots_count=len(snapshots),
            total_impressions=agg["impressions"],
            total_reach=agg["reach"],
            total_engagements=agg["engagements"],
            total_clicks=agg["clicks"],
            avg_ctr=agg["avg_ctr"],
            avg_engagement_rate=agg["avg_engagement_rate"],
            top_topics=topic_report.items[:5],
            top_clusters=cluster_report.items[:5],
            warnings=warnings,
        )

    def build_feedback_signals(self, db: Session, project_id: int) -> AnalyticsFeedbackReport:
        """Сформировать feedback-сигналы по кластерам проекта."""
        project = self._require_project(db, project_id)
        cluster_report = self.get_cluster_performance(db, project_id)
        warnings = list(cluster_report.warnings)
        if not cluster_report.items:
            warnings.append("Недостаточно данных для feedback-сигналов")

        signals: list[AnalyticsFeedbackSignal] = []
        for item in cluster_report.items:
            if item.performance_score > _BOOST_SCORE:
                signals.append(
                    AnalyticsFeedbackSignal(
                        cluster=item.cluster,
                        signal_type="boost_cluster",
                        value=10.0,
                        reason=f"Высокий performance_score {item.performance_score}",
                    )
                )
            if item.avg_engagement_rate < _LOW_ENGAGEMENT_RATE:
                signals.append(
                    AnalyticsFeedbackSignal(
                        cluster=item.cluster,
                        signal_type="review_content_format",
                        value=-5.0,
                        reason=f"Низкая вовлечённость {item.avg_engagement_rate}",
                    )
                )
            if item.total_impressions >= _MIN_IMPRESSIONS_FOR_CTA and item.avg_ctr < _LOW_CTR:
                signals.append(
                    AnalyticsFeedbackSignal(
                        cluster=item.cluster,
                        signal_type="improve_cta",
                        value=-3.0,
                        reason=(
                            f"Много показов ({item.total_impressions}), низкий CTR {item.avg_ctr}"
                        ),
                    )
                )

        return AnalyticsFeedbackReport(
            project_id=project.id,
            project_slug=project.slug,
            signals=signals,
            warnings=list(dict.fromkeys(warnings)),
        )

    # --- Внутреннее ---

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def _store(
        self,
        db: Session,
        post: Post,
        post_publication_id: int | None,
        platform: str,
        source: str,
        snapshot_at: datetime | None,
        metrics: dict[str, int],
        raw_metrics: dict[str, Any],
    ) -> PostAnalyticsSnapshot:
        impressions = metrics.get("impressions", 0)
        reach = metrics.get("reach", 0)
        views = metrics.get("views", 0)
        likes = metrics.get("likes", 0)
        reactions = metrics.get("reactions", 0)
        comments = metrics.get("comments", 0)
        shares = metrics.get("shares", 0)
        saves = metrics.get("saves", 0)
        clicks = metrics.get("clicks", 0)

        engagements = calculate_engagements(likes, reactions, comments, shares, saves)
        ctr = calculate_ctr(clicks, impressions, reach)
        engagement_rate = calculate_engagement_rate(engagements, impressions, reach)

        insert = PostAnalyticsSnapshotInsert(
            post_id=post.id,
            post_publication_id=post_publication_id,
            project_id=post.project_id,
            topic_id=post.topic_id,
            platform=platform,
            snapshot_at=snapshot_at or _utcnow(),
            impressions=impressions,
            reach=reach,
            views=views,
            likes=likes,
            reactions=reactions,
            comments=comments,
            shares=shares,
            saves=saves,
            clicks=clicks,
            ctr=ctr,
            engagement_rate=engagement_rate,
            raw_metrics=raw_metrics,
            source=source,
        )
        snapshot = analytics_repository.create_snapshot(db, insert)
        logger.info(
            "Снимок аналитики id=%s: post=%s platform=%s source=%s",
            snapshot.id,
            post.id,
            platform,
            source,
        )
        return snapshot

    @staticmethod
    def _aggregate(snapshots: Sequence[PostAnalyticsSnapshot]) -> dict[str, Any]:
        engagements = sum(
            calculate_engagements(s.likes, s.reactions, s.comments, s.shares, s.saves)
            for s in snapshots
        )
        return {
            "impressions": sum(s.impressions for s in snapshots),
            "reach": sum(s.reach for s in snapshots),
            "views": sum(s.views for s in snapshots),
            "engagements": engagements,
            "clicks": sum(s.clicks for s in snapshots),
            "avg_ctr": _avg([s.ctr for s in snapshots]),
            "avg_engagement_rate": _avg([s.engagement_rate for s in snapshots]),
        }

    @staticmethod
    def _score(agg: dict[str, Any]) -> float:
        return calculate_performance_score(
            agg["impressions"],
            agg["reach"],
            agg["engagements"],
            agg["clicks"],
            agg["avg_ctr"],
            agg["avg_engagement_rate"],
        )
