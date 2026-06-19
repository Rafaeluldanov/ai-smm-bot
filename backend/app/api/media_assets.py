"""REST API для медиа-активов (MediaAsset)."""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_media_analysis_service,
    get_media_status_service,
    get_media_sync_service,
    get_public_media_sync_service,
)
from app.integrations.yandex_disk.client import YandexDiskAuthError, YandexDiskError
from app.models.media_asset import MediaAsset
from app.repositories import media_asset_repository as repo
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.schemas.media_asset import (
    MediaAssetAnalysisResult,
    MediaAssetRead,
    MediaAssetRetagResult,
    MediaAssetStatusUpdate,
    MediaAssetSyncResult,
    MediaAssetTagsSummary,
    ShootingTaskSuggestion,
)
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import (
    InvalidMediaStatusError,
    InvalidMediaStatusTransitionError,
    MediaStatusService,
)
from app.services.project_media_paths import UnknownProjectError
from app.services.public_yandex_disk_media_sync_service import (
    PublicLinkNotConfiguredError,
    PublicYandexDiskMediaSyncService,
)
from app.services.yandex_disk_media_sync_service import (
    ProjectNotFoundError,
    YandexDiskMediaSyncService,
)

router = APIRouter(prefix="/media-assets", tags=["media-assets"])

DbSession = Annotated[Session, Depends(get_db)]
SyncService = Annotated[YandexDiskMediaSyncService, Depends(get_media_sync_service)]
PublicSyncService = Annotated[
    PublicYandexDiskMediaSyncService, Depends(get_public_media_sync_service)
]
AnalysisService = Annotated[MediaAnalysisService, Depends(get_media_analysis_service)]
StatusService = Annotated[MediaStatusService, Depends(get_media_status_service)]


def _run_sync(action: Callable[[], MediaAssetSyncResult]) -> MediaAssetSyncResult:
    """Выполнить синхронизацию и привести доменные ошибки к HTTP-кодам."""
    try:
        return action()
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnknownProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except YandexDiskAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Яндекс Диск недоступен: задайте корректный YANDEX_DISK_TOKEN",
        ) from exc
    except YandexDiskError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка Яндекс Диска: {exc}",
        ) from exc


def _project_404(action: Callable[[], MediaAssetRetagResult]) -> MediaAssetRetagResult:
    """Обернуть операцию проекта: ProjectNotFoundError -> 404."""
    try:
        return action()
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _run_public_sync(action: Callable[[], MediaAssetSyncResult]) -> MediaAssetSyncResult:
    """Выполнить публичную синхронизацию и привести ошибки к HTTP-кодам."""
    try:
        return action()
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PublicLinkNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except YandexDiskError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка публичного Яндекс Диска: {exc}",
        ) from exc


# --- Коллекция и сводки (статические пути объявляем ДО /{media_asset_id}) ---


@router.get("", response_model=list[MediaAssetRead])
def list_media_assets(
    db: DbSession,
    project_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MediaAsset]:
    """Список медиа-активов с фильтрами по проекту и статусу."""
    return repo.list_media_assets(
        db, project_id=project_id, status=status_filter, limit=limit, offset=offset
    )


@router.get("/tags/summary", response_model=MediaAssetTagsSummary)
def tags_summary(
    db: DbSession,
    analysis: AnalysisService,
    project_id: int | None = None,
) -> MediaAssetTagsSummary:
    """Сводка частот тегов по группам."""
    return MediaAssetTagsSummary(**analysis.get_tags_summary(db, project_id=project_id))


@router.get("/shooting-suggestions", response_model=list[ShootingTaskSuggestion])
def shooting_suggestions(
    project_id: int,
    db: DbSession,
    analysis: AnalysisService,
) -> list[ShootingTaskSuggestion]:
    """Рекомендации по досъёмке для проекта. 404 — проекта нет."""
    try:
        tasks = analysis.suggest_shooting_tasks(db, project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UnknownProjectError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [ShootingTaskSuggestion(**task) for task in tasks]


# --- Синхронизация и ретегирование проекта ---


@router.post("/sync/project/{project_id}", response_model=MediaAssetSyncResult)
def sync_by_project(project_id: int, db: DbSession, sync: SyncService) -> MediaAssetSyncResult:
    """Синхронизация медиа проекта по id. 404 — нет проекта; 503 — нет токена."""
    return _run_sync(lambda: sync.sync_project_media(db, project_id))


@router.post("/sync/slug/{slug}", response_model=MediaAssetSyncResult)
def sync_by_slug(slug: str, db: DbSession, sync: SyncService) -> MediaAssetSyncResult:
    """Синхронизация медиа проекта по slug. 404 — нет проекта; 503 — нет токена."""
    return _run_sync(lambda: sync.sync_project_media_by_slug(db, slug))


@router.post("/sync/public/project/{project_id}", response_model=MediaAssetSyncResult)
def sync_public_by_project(
    project_id: int, db: DbSession, sync: PublicSyncService
) -> MediaAssetSyncResult:
    """Публичная синхронизация по id проекта. 404 — нет проекта; 503 — нет публичной ссылки."""
    return _run_public_sync(lambda: sync.sync_project_media_from_public_link(db, project_id))


@router.post("/sync/public/slug/{slug}", response_model=MediaAssetSyncResult)
def sync_public_by_slug(slug: str, db: DbSession, sync: PublicSyncService) -> MediaAssetSyncResult:
    """Публичная синхронизация по slug проекта. 404 — нет проекта; 503 — нет публичной ссылки."""
    return _run_public_sync(lambda: sync.sync_project_media_by_slug_from_public_link(db, slug))


@router.post("/retag/project/{project_id}", response_model=MediaAssetRetagResult)
def retag_by_project(
    project_id: int, db: DbSession, analysis: AnalysisService
) -> MediaAssetRetagResult:
    """Повторно протегировать все медиа проекта по id. 404 — нет проекта."""
    return _project_404(
        lambda: MediaAssetRetagResult(**analysis.retag_project_media(db, project_id))
    )


@router.post("/retag/slug/{slug}", response_model=MediaAssetRetagResult)
def retag_by_slug(slug: str, db: DbSession, analysis: AnalysisService) -> MediaAssetRetagResult:
    """Повторно протегировать все медиа проекта по slug. 404 — нет проекта."""
    return _project_404(
        lambda: MediaAssetRetagResult(**analysis.retag_project_media_by_slug(db, slug))
    )


# --- Операции над одним активом (динамический {media_asset_id} — последним) ---


@router.get("/{media_asset_id}", response_model=MediaAssetRead)
def get_media_asset(media_asset_id: int, db: DbSession) -> MediaAsset:
    """Получить медиа-актив по id. Если нет — 404."""
    asset = repo.get_media_asset_by_id(db, media_asset_id)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Медиа-актив id={media_asset_id} не найден",
        )
    return asset


@router.post("/{media_asset_id}/analyze", response_model=MediaAssetAnalysisResult)
def analyze_media_asset(
    media_asset_id: int,
    db: DbSession,
    analysis: AnalysisService,
    save: bool = True,
) -> MediaAssetAnalysisResult:
    """Проанализировать медиа-актив. save=true сохраняет теги. 404 — нет актива."""
    try:
        result = analysis.analyze_media_asset(db, media_asset_id, save=save)
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return MediaAssetAnalysisResult(**result)


@router.post("/{media_asset_id}/retag", response_model=MediaAssetRead)
def retag_media_asset(media_asset_id: int, db: DbSession, analysis: AnalysisService) -> MediaAsset:
    """Повторно протегировать один медиа-актив. 404 — нет актива."""
    try:
        return analysis.retag_media_asset(db, media_asset_id)
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{media_asset_id}/status", response_model=MediaAssetRead)
def update_media_status(
    media_asset_id: int,
    payload: MediaAssetStatusUpdate,
    db: DbSession,
    status_service: StatusService,
) -> MediaAsset:
    """Сменить статус. 404 — нет актива; 422 — неизвестный статус; 409 — запрещённый переход."""
    try:
        return status_service.update_media_status(db, media_asset_id, payload.status)
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidMediaStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except InvalidMediaStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
