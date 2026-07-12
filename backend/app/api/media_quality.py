"""REST API оценки качества медиа (v0.4.6).

Все роуты — под tenant-изоляцией. Preview/оценка — бесплатны (без внешнего AI); live-
публикаций нет. Секретов/токенов и внутренних путей к файлам в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_media_quality_service, get_optional_user
from app.api.security_guards import require_media_quality_access, require_project_access
from app.models.user import User
from app.repositories import media_quality_repository
from app.services.media_quality_service import MediaQualityError, MediaQualityService

router = APIRouter(prefix="/media-quality", tags=["media-quality"])

DbSession = Annotated[Session, Depends(get_db)]
QualitySvc = Annotated[MediaQualityService, Depends(get_media_quality_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except MediaQualityError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


# --- Запросы ---


class ScoreRequest(BaseModel):
    """Оценка пачки медиа проекта."""

    platform_key: str | None = None
    limit: int = 100


class AssetScoreRequest(BaseModel):
    """Оценка одного медиа."""

    platform_key: str | None = None


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_snapshots(
    project_id: int,
    db: DbSession,
    service: QualitySvc,
    platform_key: str | None = None,
    snapshot_status: str | None = None,
    min_score: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список снимков качества проекта (фильтры платформа/статус/минимальный балл)."""
    rows = media_quality_repository.list_for_project(
        db, project_id, _platform(platform_key), snapshot_status, min_score, limit, offset
    )
    return [service._snapshot_view(r) for r in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: QualitySvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Сводка качества медиа проекта для UI."""
    return service.build_media_quality_dashboard(db, project_id, _platform(platform_key))


@router.post("/projects/{project_id}/score-preview", dependencies=[Depends(require_project_access)])
def score_preview(
    project_id: int, payload: ScoreRequest, db: DbSession, service: QualitySvc
) -> dict[str, Any]:
    """Предпросмотр оценки пачки медиа (без записи)."""
    return _run(
        lambda: service.score_project_media(
            db, project_id, _platform(payload.platform_key), limit=payload.limit, dry_run=True
        )
    )


@router.post("/projects/{project_id}/score", dependencies=[Depends(require_project_access)])
def score(
    project_id: int, payload: ScoreRequest, db: DbSession, service: QualitySvc
) -> dict[str, Any]:
    """Оценить пачку медиа проекта (пишет снимки; без внешнего AI и live)."""
    return _run(
        lambda: service.score_project_media(
            db, project_id, _platform(payload.platform_key), limit=payload.limit, dry_run=False
        )
    )


@router.post(
    "/projects/{project_id}/media-assets/{media_asset_id}/score-preview",
    dependencies=[Depends(require_project_access)],
)
def score_asset_preview(
    project_id: int,
    media_asset_id: int,
    payload: AssetScoreRequest,
    db: DbSession,
    service: QualitySvc,
) -> dict[str, Any]:
    """Предпросмотр оценки одного медиа (без записи)."""
    return _run(
        lambda: service.score_media_asset(
            db, project_id, media_asset_id, _platform(payload.platform_key), dry_run=True
        )
    )


@router.post(
    "/projects/{project_id}/media-assets/{media_asset_id}/score",
    dependencies=[Depends(require_project_access)],
)
def score_asset(
    project_id: int,
    media_asset_id: int,
    payload: AssetScoreRequest,
    db: DbSession,
    service: QualitySvc,
) -> dict[str, Any]:
    """Оценить одно медиа (пишет снимок; без внешнего AI и live)."""
    return _run(
        lambda: service.score_media_asset(
            db, project_id, media_asset_id, _platform(payload.platform_key), dry_run=False
        )
    )


# --- Роут снимка ---


@router.get("/{snapshot_id}", dependencies=[Depends(require_media_quality_access)])
def get_snapshot(snapshot_id: int, db: DbSession, service: QualitySvc) -> dict[str, Any]:
    """Один снимок качества медиа."""
    snapshot = media_quality_repository.get_by_id(db, snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return service._snapshot_view(snapshot)
