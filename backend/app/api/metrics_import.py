"""REST API импорта метрик и обратной связи обучения (v0.4.1).

Все роуты — под tenant-изоляцией (``require_project_access`` /
``require_publication_access``). Реальные внешние API по умолчанию выключены; demo/manual
работают без сети. Секретов/сырых токенов в ответах нет. Никаких live-публикаций.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_metrics_import_service, get_optional_user
from app.api.security_guards import require_project_access, require_publication_access
from app.models.user import User
from app.repositories import metric_import_run_repository
from app.services.billing_service import InsufficientBalanceError
from app.services.metrics_import_service import MetricsImportError, MetricsImportService

router = APIRouter(prefix="/metrics", tags=["metrics-import"])

DbSession = Annotated[Session, Depends(get_db)]
MetricsSvc = Annotated[MetricsImportService, Depends(get_metrics_import_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except MetricsImportError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


# --- Запросы ---


class MetricsImportRequest(BaseModel):
    """Запрос preview/run импорта метрик."""

    platform_key: str | None = None  # telegram | vk | instagram | all(None)
    source: str = "demo"  # demo | manual | api | estimated | internal
    period_start: str | None = None
    period_end: str | None = None
    depth: str = "standard"  # light | standard | deep
    idempotency_key: str | None = None


class ManualMetricsBody(BaseModel):
    """Ручной ввод метрик публикации (source=manual, бесплатно)."""

    views: int | None = None
    reach: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    followers_delta: int | None = None


class LearningRebuildRequest(BaseModel):
    """Запрос пересчёта обучения по метрикам."""

    platform_key: str | None = None
    depth: str = "standard"
    idempotency_key: str | None = None


def _platform(platform_key: str | None) -> str | None:
    if platform_key in (None, "", "all"):
        return None
    return platform_key


# --- Роуты ---


@router.get("/projects/{project_id}/imports", dependencies=[Depends(require_project_access)])
def list_imports(project_id: int, db: DbSession) -> list[dict[str, Any]]:
    """История прогонов импорта метрик проекта."""
    runs = metric_import_run_repository.list_for_project(db, project_id)
    return [MetricsImportService._mask_run(r) for r in runs]


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int, payload: MetricsImportRequest, db: DbSession, service: MetricsSvc
) -> dict[str, Any]:
    """Что было бы импортировано (без записи и без списания units)."""
    return _run(
        lambda: service.preview_import(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.source,
            payload.period_start,
            payload.period_end,
            payload.depth,
        )
    )


@router.post("/projects/{project_id}/run-dry", dependencies=[Depends(require_project_access)])
def run_dry(
    project_id: int, payload: MetricsImportRequest, db: DbSession, service: MetricsSvc
) -> dict[str, Any]:
    """Сухой прогон импорта (без записи и без списания)."""
    return _run(
        lambda: service.run_import_dry(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.source,
            payload.period_start,
            payload.period_end,
            payload.depth,
        )
    )


@router.post("/projects/{project_id}/run", dependencies=[Depends(require_project_access)])
def run_import(
    project_id: int,
    payload: MetricsImportRequest,
    db: DbSession,
    service: MetricsSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Импортировать метрики (снимки + сигналы обучения). Платно только для api-источника."""
    return _run(
        lambda: service.run_import(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.source,
            payload.depth,
            payload.period_start,
            payload.period_end,
            payload.idempotency_key,
            _uid(user),
        )
    )


@router.post(
    "/publications/{publication_id}/manual",
    dependencies=[Depends(require_publication_access)],
)
def manual_metrics(
    publication_id: int,
    payload: ManualMetricsBody,
    db: DbSession,
    service: MetricsSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Сохранить ручные метрики публикации (source=manual). Бесплатно."""
    metrics = payload.model_dump(exclude_none=True)
    return _run(lambda: service.save_manual_metrics(db, publication_id, metrics, _uid(user)))


@router.post(
    "/projects/{project_id}/learning/rebuild-preview",
    dependencies=[Depends(require_project_access)],
)
def rebuild_preview(
    project_id: int,
    payload: LearningRebuildRequest,
    db: DbSession,
    service: MetricsSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Превью пересчёта обучения по метрикам (без записи-версии и без списания)."""
    return _run(
        lambda: service.rebuild_learning_from_metrics(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.depth,
            payload.idempotency_key,
            dry_run=True,
            current_user_id=_uid(user),
        )
    )


@router.post(
    "/projects/{project_id}/learning/rebuild",
    dependencies=[Depends(require_project_access)],
)
def rebuild(
    project_id: int,
    payload: LearningRebuildRequest,
    db: DbSession,
    service: MetricsSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Пересчитать профиль обучения по метрикам (поднятие версии, платно)."""
    return _run(
        lambda: service.rebuild_learning_from_metrics(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.depth,
            payload.idempotency_key,
            dry_run=False,
            current_user_id=_uid(user),
        )
    )


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int,
    db: DbSession,
    service: MetricsSvc,
    platform: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Сводка метрик и обучения проекта для UI."""
    filters = {"platform": _platform(platform), "source": source}
    return service.build_metrics_dashboard(db, project_id, filters)
