"""REST API аналитики публикаций (Этап 8).

Статические пути (`/snapshots`, `/ingest/...`, `/fetch/...`, `/posts/...`,
`/projects/...`) объявлены до динамического `/snapshots/{snapshot_id}`.
Доменные ошибки: нет поста/публикации/проекта → 404; нет метрик → 422.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_analytics_service, get_db, get_post_analytics_service
from app.api.security_guards import (
    OptionalUser,
    SettingsDep,
    guard_project_in_body,
    require_account_member,
    require_post_access,
    require_project_access,
)
from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.repositories import analytics_repository as repo
from app.repositories import post_publication_repository
from app.repositories.post_repository import PostNotFoundError
from app.schemas.analytics import (
    AnalyticsFeedbackReport,
    AnalyticsRunRequest,
    ClusterPerformanceReport,
    ManualMetricsRequest,
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
from app.services.billing_service import InsufficientBalanceError
from app.services.post_analytics_service import PostAnalyticsError, PostAnalyticsService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/analytics", tags=["analytics"])

DbSession = Annotated[Session, Depends(get_db)]
Analytics = Annotated[AnalyticsService, Depends(get_analytics_service)]
PostAnalytics = Annotated[PostAnalyticsService, Depends(get_post_analytics_service)]

T = TypeVar("T")


def _run(action: Callable[[], T]) -> T:
    """Привести доменные ошибки аналитики к HTTP-кодам (404/422/402)."""
    try:
        return action()
    except (
        PostNotFoundError,
        PublicationNotFoundError,
        ProjectNotFoundError,
        PostAnalyticsError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except (AnalyticsInputError, ValueError) as exc:
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


@router.get(
    "/posts/{post_id}/performance",
    response_model=PostPerformanceReport,
    dependencies=[Depends(require_post_access)],
)
def post_performance(post_id: int, db: DbSession, service: Analytics) -> PostPerformanceReport:
    """Эффективность поста по всем снимкам. 404 — поста нет."""
    return _run(lambda: service.get_post_performance(db, post_id))


@router.get(
    "/projects/{project_id}/topics",
    response_model=TopicPerformanceReport,
    dependencies=[Depends(require_project_access)],
)
def topic_performance(project_id: int, db: DbSession, service: Analytics) -> TopicPerformanceReport:
    """Эффективность тем проекта. 404 — проекта нет."""
    return _run(lambda: service.get_topic_performance(db, project_id))


@router.get(
    "/projects/{project_id}/clusters",
    response_model=ClusterPerformanceReport,
    dependencies=[Depends(require_project_access)],
)
def cluster_performance(
    project_id: int, db: DbSession, service: Analytics
) -> ClusterPerformanceReport:
    """Эффективность кластеров проекта. 404 — проекта нет."""
    return _run(lambda: service.get_cluster_performance(db, project_id))


@router.get(
    "/projects/{project_id}/summary",
    response_model=ProjectAnalyticsSummary,
    dependencies=[Depends(require_project_access)],
)
def project_summary(project_id: int, db: DbSession, service: Analytics) -> ProjectAnalyticsSummary:
    """Сводная аналитика проекта. 404 — проекта нет."""
    return _run(lambda: service.get_project_summary(db, project_id))


@router.get(
    "/projects/{project_id}/feedback",
    response_model=AnalyticsFeedbackReport,
    dependencies=[Depends(require_project_access)],
)
def project_feedback(project_id: int, db: DbSession, service: Analytics) -> AnalyticsFeedbackReport:
    """Feedback-сигналы проекта. 404 — проекта нет."""
    return _run(lambda: service.build_feedback_signals(db, project_id))


# --- Аналитика постов v0.2.13: анализ контента, карточки, календарь, отчёты ---


@router.post(
    "/posts/{post_id}/manual-metrics",
    response_model=PostAnalyticsSnapshotRead,
    dependencies=[Depends(require_post_access)],
)
def save_manual_metrics(
    post_id: int, payload: ManualMetricsRequest, db: DbSession, service: Analytics
) -> PostAnalyticsSnapshotRead:
    """Сохранить метрики поста вручную (source=manual). БЕСПЛАТНО (0 units)."""
    platform = payload.platform
    if not platform:
        pubs = post_publication_repository.list_publications(db, post_id=post_id)
        platform = pubs[0].platform if pubs else "manual"
    create = PostAnalyticsSnapshotCreate(
        post_id=post_id,
        platform=platform,
        source="manual",
        views=payload.views,
        reach=payload.reach,
        impressions=payload.impressions,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        saves=payload.saves,
        clicks=payload.clicks,
        raw_metrics={"followers_delta": payload.followers_delta},
    )
    return _run(lambda: service.ingest_snapshot(db, create))


@router.get("/posts/{post_id}/card", dependencies=[Depends(require_post_access)])
def post_analytics_card(
    post_id: int, db: DbSession, service: PostAnalytics, depth: str = "light"
) -> dict[str, Any]:
    """Карточка анализа поста (light|standard|deep). Не списывает units (просмотр)."""
    return _run(lambda: service.build_post_analytics_card(db, post_id, depth))


@router.get("/projects/{project_id}/posts", dependencies=[Depends(require_project_access)])
def project_posts_for_analytics(
    project_id: int,
    db: DbSession,
    service: PostAnalytics,
    platform: str | None = None,
    post_status: str | None = None,
) -> list[dict[str, Any]]:
    """Список постов проекта для аналитики (с фильтрами платформы/статуса)."""
    return service.list_project_posts_for_analytics(db, project_id, platform, post_status)


@router.get("/projects/{project_id}/calendar", dependencies=[Depends(require_project_access)])
def project_calendar(
    project_id: int,
    db: DbSession,
    service: PostAnalytics,
    month: str | None = None,
    platform: str | None = None,
) -> dict[str, Any]:
    """Календарь публикаций проекта по дням (счётчики статусов + посты)."""
    return service.build_calendar(db, project_id, month, platform)


@router.post("/accounts/{account_id}/preview", dependencies=[Depends(require_account_member)])
def analytics_cost_preview(
    account_id: int,
    payload: AnalyticsRunRequest,
    db: DbSession,
    service: PostAnalytics,
    user: OptionalUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Оценка стоимости отчёта (units) и доступность по балансу. Бесплатно."""
    guard_project_in_body(db, settings, user, payload.project_id)
    posts = service.list_project_posts_for_analytics(
        db, payload.project_id, payload.platform, payload.status
    )
    return _run(
        lambda: service.preview_analytics_cost(db, account_id, payload.depth, len(posts) or 1)
    )


@router.post("/accounts/{account_id}/run-dry", dependencies=[Depends(require_account_member)])
def analytics_run_dry(
    account_id: int,
    payload: AnalyticsRunRequest,
    db: DbSession,
    service: PostAnalytics,
    user: OptionalUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Dry-run отчёта: результат + estimated units, БЕЗ списания."""
    guard_project_in_body(db, settings, user, payload.project_id)
    return _run(
        lambda: service.run_analytics_dry(
            db, account_id, payload.project_id, payload.depth, payload.platform, payload.status
        )
    )


@router.post("/accounts/{account_id}/run", dependencies=[Depends(require_account_member)])
def analytics_run(
    account_id: int,
    payload: AnalyticsRunRequest,
    db: DbSession,
    service: PostAnalytics,
    user: OptionalUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Платный запуск отчёта: списывает units (402 при нехватке баланса)."""
    guard_project_in_body(db, settings, user, payload.project_id)
    return _run(
        lambda: service.run_analytics(
            db,
            account_id,
            payload.project_id,
            payload.depth,
            payload.platform,
            payload.status,
            payload.idempotency_key,
        )
    )


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
