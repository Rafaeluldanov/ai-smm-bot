"""REST API аналитики публикаций (Этап 8).

Статические пути (`/snapshots`, `/ingest/...`, `/fetch/...`, `/posts/...`,
`/projects/...`) объявлены до динамического `/snapshots/{snapshot_id}`.
Доменные ошибки: нет поста/публикации/проекта → 404; нет метрик → 422.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_analytics_service, get_db
from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import analytics_repository as repo
from app.repositories.post_repository import PostNotFoundError
from app.schemas.analytics import (
    AnalyticsFeedbackReport,
    ClusterPerformanceReport,
    PostAnalyticsIngestRequest,
    PostAnalyticsIngestResult,
    PostAnalyticsSnapshotCreate,
    PostAnalyticsSnapshotRead,
    PostPerformanceReport,
    ProjectAnalyticsSummary,
    TopicPerformanceReport,
)
from app.services.analytics_service import (
    AnalyticsInputError,
    AnalyticsService,
    PublicationNotFoundError,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/analytics", tags=["analytics"])

DbSession = Annotated[Session, Depends(get_db)]
Analytics = Annotated[AnalyticsService, Depends(get_analytics_service)]

T = TypeVar("T")


def _run(action: Callable[[], T]) -> T:
    """Привести доменные ошибки аналитики к HTTP-кодам (404/422)."""
    try:
        return action()
    except (PostNotFoundError, PublicationNotFoundError, ProjectNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AnalyticsInputError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# --- Снимки (статические пути ДО /snapshots/{snapshot_id}) ---


@router.get("/snapshots", response_model=list[PostAnalyticsSnapshotRead])
def list_snapshots(
    db: DbSession,
    post_id: int | None = None,
    project_id: int | None = None,
    topic_id: int | None = None,
    platform: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PostAnalyticsSnapshot]:
    """Список снимков с фильтрами по посту, проекту, теме и платформе."""
    return repo.list_snapshots(
        db,
        post_id=post_id,
        project_id=project_id,
        topic_id=topic_id,
        platform=platform,
        limit=limit,
        offset=offset,
    )


@router.post("/snapshots", response_model=PostAnalyticsSnapshotRead)
def create_snapshot(
    payload: PostAnalyticsSnapshotCreate, db: DbSession, service: Analytics
) -> PostAnalyticsSnapshotRead:
    """Создать снимок вручную (с расчётом CTR/ER). 404 — поста нет."""
    return _run(lambda: service.ingest_snapshot(db, payload))


@router.post("/ingest/publication/{publication_id}", response_model=PostAnalyticsIngestResult)
def ingest_publication(
    publication_id: int,
    db: DbSession,
    service: Analytics,
    payload: PostAnalyticsIngestRequest | None = None,
) -> PostAnalyticsIngestResult:
    """Загрузить метрики по публикации. 404 — нет публикации; 422 — нет метрик."""
    request = payload or PostAnalyticsIngestRequest()
    snapshot = _run(
        lambda: service.ingest_for_publication(
            db, publication_id, source=request.source, metrics=request.metrics
        )
    )
    return PostAnalyticsIngestResult(
        post_id=snapshot.post_id,
        post_publication_id=snapshot.post_publication_id,
        snapshot=snapshot,
    )


@router.post("/fetch/publication/{publication_id}", response_model=PostAnalyticsIngestResult)
def fetch_publication(
    publication_id: int, db: DbSession, service: Analytics
) -> PostAnalyticsIngestResult:
    """Получить метрики у fake-провайдера и сохранить снимок. 404 — нет публикации."""
    snapshot = _run(lambda: service.fetch_and_store_for_publication(db, publication_id))
    return PostAnalyticsIngestResult(
        post_id=snapshot.post_id,
        post_publication_id=snapshot.post_publication_id,
        snapshot=snapshot,
    )


# --- Отчёты ---


@router.get("/posts/{post_id}/performance", response_model=PostPerformanceReport)
def post_performance(post_id: int, db: DbSession, service: Analytics) -> PostPerformanceReport:
    """Эффективность поста по всем снимкам. 404 — поста нет."""
    return _run(lambda: service.get_post_performance(db, post_id))


@router.get("/projects/{project_id}/topics", response_model=TopicPerformanceReport)
def topic_performance(project_id: int, db: DbSession, service: Analytics) -> TopicPerformanceReport:
    """Эффективность тем проекта. 404 — проекта нет."""
    return _run(lambda: service.get_topic_performance(db, project_id))


@router.get("/projects/{project_id}/clusters", response_model=ClusterPerformanceReport)
def cluster_performance(
    project_id: int, db: DbSession, service: Analytics
) -> ClusterPerformanceReport:
    """Эффективность кластеров проекта. 404 — проекта нет."""
    return _run(lambda: service.get_cluster_performance(db, project_id))


@router.get("/projects/{project_id}/summary", response_model=ProjectAnalyticsSummary)
def project_summary(project_id: int, db: DbSession, service: Analytics) -> ProjectAnalyticsSummary:
    """Сводная аналитика проекта. 404 — проекта нет."""
    return _run(lambda: service.get_project_summary(db, project_id))


@router.get("/projects/{project_id}/feedback", response_model=AnalyticsFeedbackReport)
def project_feedback(project_id: int, db: DbSession, service: Analytics) -> AnalyticsFeedbackReport:
    """Feedback-сигналы проекта. 404 — проекта нет."""
    return _run(lambda: service.build_feedback_signals(db, project_id))


# --- Один снимок (динамический {snapshot_id} — последним) ---


@router.get("/snapshots/{snapshot_id}", response_model=PostAnalyticsSnapshotRead)
def get_snapshot(snapshot_id: int, db: DbSession) -> PostAnalyticsSnapshot:
    """Получить снимок по id. Если нет — 404."""
    snapshot = repo.get_snapshot_by_id(db, snapshot_id)
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Снимок id={snapshot_id} не найден",
        )
    return snapshot
