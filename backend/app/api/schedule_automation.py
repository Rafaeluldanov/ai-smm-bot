"""API движка автоматизации расписаний (безопасный, без live-публикации).

Все роуты под ``require_project_access`` (tenant-изоляция). ``run-due`` создаёт только
draft/needs_review + PostPublication (pending/scheduled), списывает units и пишет логи —
живой публикации НЕТ. Секретов/токенов в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_guards import (
    OptionalUser,
    SettingsDep,
    guard_project_in_body,
    require_project_access,
)
from app.services.schedule_automation_service import (
    ScheduleAutomationError,
    ScheduleAutomationService,
    get_schedule_automation_service,
)

router = APIRouter(prefix="/schedule", tags=["schedule-automation"])

DbSession = Annotated[Session, Depends(get_db)]
SchedSvc = Annotated[ScheduleAutomationService, Depends(get_schedule_automation_service)]


class ScheduleDueRequest(BaseModel):
    """Запрос preview/run по due-задачам расписания."""

    account_id: int
    date: str | None = None
    platform_key: str | None = None


_T = TypeVar("_T")


def _guard(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except ScheduleAutomationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/projects/{project_id}/tasks", dependencies=[Depends(require_project_access)])
def list_tasks(
    project_id: int, db: DbSession, service: SchedSvc, platform_key: str | None = None
) -> list[dict[str, Any]]:
    """Карточки задач расписания проекта (готовность к запуску, connection status)."""
    return service.list_schedule_tasks(db, project_id, platform_key)


@router.get("/projects/{project_id}/runs", dependencies=[Depends(require_project_access)])
def list_runs(
    project_id: int,
    db: DbSession,
    service: SchedSvc,
    platform_key: str | None = None,
    run_status: str | None = None,
) -> list[dict[str, Any]]:
    """История прогонов расписания проекта (фильтр по платформе/статусу)."""
    return service.list_runs(db, project_id, platform_key, run_status)


@router.post("/projects/{project_id}/preview-due", dependencies=[Depends(require_project_access)])
def preview_due(
    project_id: int, payload: ScheduleDueRequest, db: DbSession, service: SchedSvc
) -> dict[str, Any]:
    """Что было бы сделано по due-задачам (без записи в БД)."""
    return _guard(
        lambda: service.preview_due_runs(
            db, payload.account_id, project_id, payload.date, None, payload.platform_key
        )
    )


@router.post("/projects/{project_id}/run-due-dry", dependencies=[Depends(require_project_access)])
def run_due_dry(
    project_id: int, payload: ScheduleDueRequest, db: DbSession, service: SchedSvc
) -> dict[str, Any]:
    """Dry-run due-задач (без записи, для кнопки «Preview due»)."""
    return _guard(
        lambda: service.run_due_dry(
            db, payload.account_id, project_id, payload.date, None, payload.platform_key
        )
    )


@router.post("/projects/{project_id}/run-due", dependencies=[Depends(require_project_access)])
def run_due(
    project_id: int, payload: ScheduleDueRequest, db: DbSession, service: SchedSvc
) -> dict[str, Any]:
    """Создать draft/needs_review по due-задачам (идемпотентно). Live-публикации НЕТ."""
    return _guard(
        lambda: service.run_due(
            db, payload.account_id, project_id, payload.date, None, payload.platform_key
        )
    )


@router.get("/runs/{run_id}")
def get_run(
    run_id: int, db: DbSession, service: SchedSvc, user: OptionalUser, settings: SettingsDep
) -> dict[str, Any]:
    """Один прогон расписания (с проверкой доступа к его проекту)."""
    from app.repositories import schedule_run_repository

    run = schedule_run_repository.get_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Прогон не найден")
    guard_project_in_body(db, settings, user, run.project_id)
    masked = service.get_run(db, run.project_id, run_id)
    if masked is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Прогон не найден")
    return masked


@router.post("/runs/{run_id}/retry-dry")
def retry_dry(
    run_id: int, db: DbSession, service: SchedSvc, user: OptionalUser, settings: SettingsDep
) -> dict[str, Any]:
    """Безопасный preview-повтор прогона (dry-run, без записи и без списания)."""
    from app.repositories import schedule_run_repository

    run = schedule_run_repository.get_by_id(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Прогон не найден")
    guard_project_in_body(db, settings, user, run.project_id)
    return _guard(
        lambda: service.run_due_dry(
            db, run.account_id or 0, run.project_id, run.run_date, None, run.platform_key
        )
    )
