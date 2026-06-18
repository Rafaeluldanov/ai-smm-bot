"""REST API автономных прогонов (Этап 10).

Статические пути (`/run`, `/dry-run`, `/run/project/{id}`, `/run/slug/{slug}`)
объявлены до динамического `/{run_id}`. Доменные ошибки: нет проекта/прогона →
404; некорректный режим/настройки → 422.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_autonomous_pipeline_service, get_db
from app.models.autonomous_run import AutonomousRun
from app.models.autonomous_run_step import AutonomousRunStep
from app.repositories import autonomous_run_repository as repo
from app.schemas.autonomous import (
    AutonomousRunRead,
    AutonomousRunReport,
    AutonomousRunRequest,
    AutonomousRunResult,
    AutonomousRunStepRead,
)
from app.services.autonomous_pipeline_service import (
    AutonomousPipelineService,
    AutonomousRunNotFoundError,
    AutonomousValidationError,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/autonomous-runs", tags=["autonomous-runs"])

DbSession = Annotated[Session, Depends(get_db)]
PipelineService = Annotated[AutonomousPipelineService, Depends(get_autonomous_pipeline_service)]

T = TypeVar("T")


def _run(action: Callable[[], T]) -> T:
    """Привести доменные ошибки к HTTP-кодам (404/422)."""
    try:
        return action()
    except (ProjectNotFoundError, AutonomousRunNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AutonomousValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# --- Запуск (статические пути ДО /{run_id}) ---


@router.get("", response_model=list[AutonomousRunRead])
def list_runs(
    db: DbSession,
    project_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    mode: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AutonomousRun]:
    """Список прогонов с фильтрами по проекту, статусу и режиму."""
    return repo.list_runs(
        db, project_id=project_id, status=status_filter, mode=mode, limit=limit, offset=offset
    )


@router.post("/run", response_model=AutonomousRunResult)
def run(
    payload: AutonomousRunRequest, db: DbSession, service: PipelineService
) -> AutonomousRunResult:
    """Запустить автономный прогон. 404 — нет проекта; 422 — режим/настройки."""
    return _run(lambda: service.run_pipeline(db, payload))


@router.post("/dry-run", response_model=AutonomousRunResult)
def dry_run(
    payload: AutonomousRunRequest, db: DbSession, service: PipelineService
) -> AutonomousRunResult:
    """Сухой прогон (без создания тем/постов/публикаций). 404 — нет проекта."""
    return _run(lambda: service.dry_run_pipeline(db, payload))


@router.post("/run/project/{project_id}", response_model=AutonomousRunResult)
def run_by_project(
    project_id: int, payload: AutonomousRunRequest, db: DbSession, service: PipelineService
) -> AutonomousRunResult:
    """Запустить прогон по id проекта."""
    request = payload.model_copy(update={"project_id": project_id})
    return _run(lambda: service.run_pipeline(db, request))


@router.post("/run/slug/{slug}", response_model=AutonomousRunResult)
def run_by_slug(
    slug: str, payload: AutonomousRunRequest, db: DbSession, service: PipelineService
) -> AutonomousRunResult:
    """Запустить прогон по slug проекта."""
    return _run(lambda: service.run_for_project_slug(db, slug, payload))


# --- Операции над одним прогоном (динамический {run_id} — последним) ---


@router.get("/{run_id}", response_model=AutonomousRunRead)
def get_run(run_id: int, db: DbSession) -> AutonomousRun:
    """Получить прогон по id. Если нет — 404."""
    run_obj = repo.get_run_by_id(db, run_id)
    if run_obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Прогон id={run_id} не найден"
        )
    return run_obj


@router.get("/{run_id}/steps", response_model=list[AutonomousRunStepRead])
def get_run_steps(run_id: int, db: DbSession) -> list[AutonomousRunStep]:
    """Получить шаги прогона. 404 — прогона нет."""
    if repo.get_run_by_id(db, run_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Прогон id={run_id} не найден"
        )
    return repo.list_steps(db, run_id)


@router.get("/{run_id}/report", response_model=AutonomousRunReport)
def get_run_report(run_id: int, db: DbSession, service: PipelineService) -> AutonomousRunReport:
    """Получить отчёт по прогону. 404 — прогона нет."""
    return _run(lambda: service.build_report(db, run_id))
