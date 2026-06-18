"""Фоновые задачи планировщика.

Сигнатуры периодических заданий. Публикация постов (Этап 7) реализована как
``publish_due_publications_job`` с явной передачей сессии и сервиса — это удобно
для тестов и не требует бесконечного цикла или сети.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import post_publication_repository
from app.repositories.post_repository import PostNotFoundError
from app.schemas.analytics import PostAnalyticsSnapshotRead
from app.schemas.autonomous import AutonomousRunRequest, AutonomousRunResult
from app.schemas.post_publication import DuePublicationsResult
from app.services.analytics_provider import AnalyticsProviderError
from app.services.analytics_service import AnalyticsService, PublicationNotFoundError
from app.services.autonomous_pipeline_service import AutonomousPipelineService
from app.services.post_publication_service import PostPublicationService

logger = get_logger(__name__)


def scan_yandex_disk_job() -> None:
    """Просканировать Яндекс Диск и обновить медиа-активы (Этап 2)."""
    logger.info("scan_yandex_disk_job: заглушка Этапа 0")


def refresh_topics_job() -> None:
    """Пересчитать темы-кандидаты для активных проектов (Этап 4)."""
    logger.info("refresh_topics_job: заглушка Этапа 0")


def publish_due_publications_job(
    db: Session, service: PostPublicationService, now: datetime | None = None
) -> DuePublicationsResult:
    """Опубликовать созревшие публикации одним проходом (без цикла и сети).

    Сессия и сервис передаются явно — это делает задачу тестируемой и
    переиспользуемой из CLI/планировщика.
    """
    result = service.publish_due_publications(db, now)
    logger.info(
        "publish_due_publications_job: постов=%d, опубликовано=%d, ошибок=%d, пропущено=%d",
        result.processed_posts,
        result.published_count,
        result.failed_count,
        result.skipped_count,
    )
    return result


def publish_scheduled_posts_job() -> None:
    """Совместимая обёртка-заглушка (реальный запуск — через job выше с db/service)."""
    logger.info(
        "publish_scheduled_posts_job: используйте publish_due_publications_job(db, service)"
    )


def collect_publication_analytics_job(
    db: Session,
    service: AnalyticsService,
    publication_ids: list[int] | None = None,
) -> list[PostAnalyticsSnapshotRead]:
    """Собрать аналитику публикаций (через fake-провайдер, без сети).

    Если ``publication_ids`` не заданы — обрабатываются опубликованные публикации.
    Ошибки по отдельной публикации логируются и не роняют весь проход.
    """
    if publication_ids is None:
        publication_ids = [
            publication.id
            for publication in post_publication_repository.list_publications(
                db, status="published", limit=10000
            )
        ]

    snapshots: list[PostAnalyticsSnapshotRead] = []
    for publication_id in publication_ids:
        try:
            snapshots.append(service.fetch_and_store_for_publication(db, publication_id))
        except (PublicationNotFoundError, PostNotFoundError, AnalyticsProviderError) as exc:
            logger.warning("collect_publication_analytics_job: %s", exc)

    logger.info("collect_publication_analytics_job: собрано снимков=%d", len(snapshots))
    return snapshots


def autonomous_weekly_run_job(
    db: Session,
    service: AutonomousPipelineService,
    project_slug: str,
    request: AutonomousRunRequest | None = None,
) -> AutonomousRunResult:
    """Еженедельный автономный прогон по проекту (один проход, без цикла и сети).

    По умолчанию запускается в режиме ``semi_auto`` (посты уходят на согласование).
    Сессия и сервис передаются явно — задача тестируется с fake-сервисами.
    """
    effective = request or AutonomousRunRequest(project_slug=project_slug, mode="semi_auto")
    result = service.run_for_project_slug(db, project_slug, effective)
    logger.info(
        "autonomous_weekly_run_job: проект=%s статус=%s постов=%d",
        project_slug,
        result.run.status,
        result.generated_posts,
    )
    return result
