"""REST API улучшения медиа (производные варианты MediaAssetVariant).

Улучшение создаёт КОПИИ изображений; оригиналы ``MediaAsset`` не меняются.
Видео пропускаются. Спорные правки получают статус ``needs_review``.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_media_enhancement_service
from app.models.media_asset_variant import MediaAssetVariant
from app.repositories import media_asset_variant_repository as repo
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.repositories.media_asset_variant_repository import MediaAssetVariantNotFoundError
from app.schemas.media_enhancement import (
    MediaAssetVariantRead,
    MediaAssetVariantStatusUpdate,
    MediaEnhancementRequest,
    MediaEnhancementResult,
    MediaEnhancementSummary,
    ProjectMediaEnhancementRequest,
    ProjectMediaEnhancementResult,
)
from app.services.image_enhancement_processor import ImageEnhancementError
from app.services.media_download_service import (
    MediaDownloadError,
    MediaDownloadNotConfiguredError,
    MediaSourceNotSupportedError,
)
from app.services.media_enhancement_service import (
    MediaEnhancementService,
    VariantAlreadyExistsError,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/media-enhancements", tags=["media-enhancements"])

DbSession = Annotated[Session, Depends(get_db)]
EnhancementService = Annotated[MediaEnhancementService, Depends(get_media_enhancement_service)]

# Допустимые статусы варианта (для PATCH).
_ALLOWED_VARIANT_STATUSES = {"created", "needs_review", "approved", "rejected", "failed"}


def _run_enhance(action: Callable[[], MediaEnhancementResult]) -> MediaEnhancementResult:
    """Выполнить улучшение и привести доменные ошибки к HTTP-кодам."""
    try:
        return action()
    except MediaAssetNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except VariantAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except MediaDownloadNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except MediaSourceNotSupportedError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImageEnhancementError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MediaDownloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Ошибка загрузки медиа: {exc}"
        ) from exc


# --- Коллекция и сводки (статические пути объявляем ДО /{variant_id}) ---


@router.get("", response_model=list[MediaAssetVariantRead])
def list_variants(
    db: DbSession,
    media_asset_id: int | None = None,
    project_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    variant_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MediaAssetVariant]:
    """Список производных вариантов с фильтрами."""
    return repo.list_variants(
        db,
        media_asset_id=media_asset_id,
        project_id=project_id,
        status=status_filter,
        variant_type=variant_type,
        limit=limit,
        offset=offset,
    )


@router.get("/summary", response_model=MediaEnhancementSummary)
def enhancement_summary(
    db: DbSession,
    service: EnhancementService,
    project_id: int | None = None,
) -> MediaEnhancementSummary:
    """Сводка по вариантам (по статусам и типам)."""
    return service.get_enhancement_summary(db, project_id=project_id)


@router.post("/media/{media_asset_id}/enhance", response_model=MediaEnhancementResult)
def enhance_media(
    media_asset_id: int,
    db: DbSession,
    service: EnhancementService,
    payload: MediaEnhancementRequest | None = None,
) -> MediaEnhancementResult:
    """Улучшить медиа-актив (создать копию). 404 — нет актива; 409 — уже улучшено;
    400 — формат/источник не поддержан; 503 — загрузчик не настроен."""
    request = payload or MediaEnhancementRequest()
    return _run_enhance(lambda: service.enhance_media_asset(db, media_asset_id, request))


@router.post("/project", response_model=ProjectMediaEnhancementResult)
def enhance_project(
    payload: ProjectMediaEnhancementRequest,
    db: DbSession,
    service: EnhancementService,
) -> ProjectMediaEnhancementResult:
    """Пакетно улучшить медиа проекта. 404 — проект не найден."""
    try:
        return service.enhance_project_media(db, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Операции над одним вариантом (динамический {variant_id} — последним) ---


@router.patch("/{variant_id}/status", response_model=MediaAssetVariantRead)
def update_variant_status(
    variant_id: int,
    payload: MediaAssetVariantStatusUpdate,
    db: DbSession,
) -> MediaAssetVariant:
    """Сменить статус варианта. 404 — нет варианта; 422 — неизвестный статус."""
    if payload.status not in _ALLOWED_VARIANT_STATUSES:
        allowed = ", ".join(sorted(_ALLOWED_VARIANT_STATUSES))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестный статус '{payload.status}'. Допустимо: {allowed}",
        )
    try:
        return repo.mark_variant_status(db, variant_id, payload.status)
    except MediaAssetVariantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{variant_id}", response_model=MediaAssetVariantRead)
def get_variant(variant_id: int, db: DbSession) -> MediaAssetVariant:
    """Получить вариант по id. 404 — не найден."""
    variant = repo.get_variant_by_id(db, variant_id)
    if variant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Вариант медиа id={variant_id} не найден",
        )
    return variant
