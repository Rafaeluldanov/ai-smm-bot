"""REST API fingerprint и дедупликации медиа (v0.4.7).

Все роуты — под tenant-изоляцией. Preview/расчёт/кластеризация — бесплатны (локально, без
внешнего AI). Файлы НЕ удаляются. Секретов/токенов, raw bytes и внутренних путей нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_db,
    get_media_fingerprint_service,
    get_media_similarity_service,
    get_optional_user,
)
from app.api.security_guards import (
    require_media_cluster_access,
    require_media_fingerprint_access,
    require_project_access,
)
from app.models.user import User
from app.repositories import media_duplicate_cluster_repository, media_fingerprint_repository
from app.services.media_fingerprint_service import MediaFingerprintError, MediaFingerprintService
from app.services.media_similarity_service import MediaSimilarityService

router = APIRouter(prefix="/media-fingerprints", tags=["media-fingerprints"])

DbSession = Annotated[Session, Depends(get_db)]
FpSvc = Annotated[MediaFingerprintService, Depends(get_media_fingerprint_service)]
SimSvc = Annotated[MediaSimilarityService, Depends(get_media_similarity_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")

_REVIEW_ACTIONS = {
    "reviewed": (media_duplicate_cluster_repository.mark_reviewed, "media_duplicate.reviewed"),
    "ignored": (media_duplicate_cluster_repository.mark_ignored, "media_duplicate.ignored"),
    "resolved": (media_duplicate_cluster_repository.mark_resolved, "media_duplicate.resolved"),
}


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except MediaFingerprintError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _cluster_view(cluster: Any) -> dict[str, Any]:
    """Безопасный вид кластера дублей (без путей/секретов)."""
    return {
        "id": cluster.id,
        "project_id": cluster.project_id,
        "status": cluster.status,
        "cluster_type": cluster.cluster_type,
        "canonical_media_asset_id": cluster.canonical_media_asset_id,
        "member_media_asset_ids": list(cluster.member_media_asset_ids or []),
        "member_fingerprint_ids": list(cluster.member_fingerprint_ids or []),
        "similarity_score": round(cluster.similarity_score, 3),
        "reasons": list(cluster.reasons or []),
        "recommended_actions": list(cluster.recommended_actions or []),
        "reviewed_at": cluster.reviewed_at.isoformat() if cluster.reviewed_at else None,
        "created_at": cluster.created_at.isoformat() if cluster.created_at else None,
    }


# --- Запросы ---


class CalcRequest(BaseModel):
    """Расчёт fingerprint пачки медиа."""

    limit: int = 100
    dry_run: bool = False


class DuplicatesRequest(BaseModel):
    """Построение кластеров дублей."""

    dry_run: bool = False


class ReviewRequest(BaseModel):
    """Разметка кластера: reviewed | ignored | resolved."""

    action: str = "reviewed"


# --- Fingerprint: список / просмотр ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_fingerprints(
    project_id: int,
    db: DbSession,
    service: FpSvc,
    fingerprint_status: str | None = None,
    media_asset_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список fingerprint проекта (фильтры статус/медиа)."""
    rows = media_fingerprint_repository.list_for_project(
        db, project_id, fingerprint_status, media_asset_id, limit, offset
    )
    return [service.snapshot_view(r) for r in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(project_id: int, db: DbSession, similarity: SimSvc) -> dict[str, Any]:
    """Сводка fingerprint/дублей проекта для UI."""
    return similarity.build_duplicate_dashboard(db, project_id)


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview_fingerprints(
    project_id: int, payload: CalcRequest, db: DbSession, service: FpSvc
) -> dict[str, Any]:
    """Предпросмотр расчёта fingerprint пачки (без записи)."""
    return _run(
        lambda: service.calculate_project_fingerprints(
            db, project_id, limit=payload.limit, dry_run=True
        )
    )


@router.post("/projects/{project_id}/calculate", dependencies=[Depends(require_project_access)])
def calculate_fingerprints(
    project_id: int, payload: CalcRequest, db: DbSession, service: FpSvc
) -> dict[str, Any]:
    """Рассчитать fingerprint пачки медиа (пишет при dry_run=false; локально, без AI)."""
    return _run(
        lambda: service.calculate_project_fingerprints(
            db, project_id, limit=payload.limit, dry_run=payload.dry_run
        )
    )


@router.post(
    "/projects/{project_id}/media-assets/{media_asset_id}/preview",
    dependencies=[Depends(require_project_access)],
)
def preview_asset_fingerprint(
    project_id: int, media_asset_id: int, db: DbSession, service: FpSvc
) -> dict[str, Any]:
    """Предпросмотр fingerprint одного медиа (без записи)."""
    return _run(
        lambda: service.calculate_fingerprint_for_asset(
            db, project_id, media_asset_id, dry_run=True
        )
    )


@router.post(
    "/projects/{project_id}/media-assets/{media_asset_id}/calculate",
    dependencies=[Depends(require_project_access)],
)
def calculate_asset_fingerprint(
    project_id: int, media_asset_id: int, db: DbSession, service: FpSvc
) -> dict[str, Any]:
    """Рассчитать fingerprint одного медиа (пишет; локально, без AI)."""
    return _run(
        lambda: service.calculate_fingerprint_for_asset(
            db, project_id, media_asset_id, dry_run=False
        )
    )


# --- Дубли: кластеры ---


@router.get("/projects/{project_id}/duplicates", dependencies=[Depends(require_project_access)])
def list_duplicates(
    project_id: int,
    db: DbSession,
    cluster_status: str | None = None,
    cluster_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Список кластеров дублей проекта."""
    rows = media_duplicate_cluster_repository.list_for_project(
        db, project_id, cluster_status, cluster_type, limit
    )
    return [_cluster_view(c) for c in rows]


@router.post(
    "/projects/{project_id}/duplicates/preview", dependencies=[Depends(require_project_access)]
)
def preview_duplicates(project_id: int, db: DbSession, similarity: SimSvc) -> dict[str, Any]:
    """Предпросмотр кластеров дублей (без записи)."""
    return similarity.find_duplicate_clusters(db, project_id, dry_run=True)


@router.post(
    "/projects/{project_id}/duplicates/calculate", dependencies=[Depends(require_project_access)]
)
def calculate_duplicates(
    project_id: int, payload: DuplicatesRequest, db: DbSession, similarity: SimSvc
) -> dict[str, Any]:
    """Построить кластеры дублей (пишет при dry_run=false; файлы не удаляются)."""
    return similarity.find_duplicate_clusters(db, project_id, dry_run=payload.dry_run)


@router.post(
    "/projects/{project_id}/duplicates/{cluster_id}/review",
    dependencies=[Depends(require_project_access), Depends(require_media_cluster_access)],
)
def review_cluster(
    project_id: int,
    cluster_id: int,
    payload: ReviewRequest,
    db: DbSession,
    user: OptUser,
) -> dict[str, Any]:
    """Разметить кластер: reviewed | ignored | resolved. Удаления/скрытия файлов нет."""
    cluster = media_duplicate_cluster_repository.get_by_id(db, cluster_id)
    if cluster is None or cluster.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    entry = _REVIEW_ACTIONS.get(payload.action)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="action: reviewed | ignored | resolved",
        )
    mark_fn, audit_action = entry
    updated = mark_fn(db, cluster, user.id if user is not None else None)
    from app.services.audit_log_service import AuditLogService

    AuditLogService().record(
        db,
        audit_action,
        account_id=updated.account_id,
        project_id=project_id,
        entity_type="media_duplicate_cluster",
        metadata={"cluster_id": cluster_id, "status": updated.status},
    )
    return _cluster_view(updated)


# --- Роут fingerprint ---


@router.get("/{fingerprint_id}", dependencies=[Depends(require_media_fingerprint_access)])
def get_fingerprint(fingerprint_id: int, db: DbSession, service: FpSvc) -> dict[str, Any]:
    """Один fingerprint медиа."""
    row = media_fingerprint_repository.get_by_id(db, fingerprint_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return service.snapshot_view(row)
