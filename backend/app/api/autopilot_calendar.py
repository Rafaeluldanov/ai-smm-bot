"""REST API Calendar Assistant автопилота — v0.5.8.

Клиентский слой «выберите цель и частоту — Botfleet построит календарь автопостинга»: пресеты,
рекомендация, предпросмотр, создание (в т.ч. dry-run), применение к автопилоту, пауза/возобновление,
дашборд. Всё под project-гардом. Секретов/сырых токенов в ответах нет; построение и применение
календаря НЕ публикует и НЕ включает live-флаги; реальных внешних вызовов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_autopilot_calendar_assistant_service,
    get_current_user,
    get_db,
)
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.autopilot_calendar_assistant_service import (
    AutopilotCalendarAssistantService,
    CalendarAssistantError,
)

router = APIRouter(
    prefix="/autopilot-calendar",
    tags=["autopilot-calendar"],
    dependencies=[Depends(require_project_access)],
)

DbSession = Annotated[Session, Depends(get_db)]
CalendarSvc = Annotated[
    AutopilotCalendarAssistantService, Depends(get_autopilot_calendar_assistant_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except CalendarAssistantError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class CalendarPreviewRequest(BaseModel):
    """Параметры календаря (клиентская форма): цель + частота + время + площадки."""

    preset: str | None = None
    goal: str | None = None
    platforms: list[str] = []
    weekdays: list[int] | None = None
    publish_times: list[str] = []
    posts_per_day: int | None = None
    timezone: str | None = None
    time_strategy: str | None = None
    start_date: str | None = None
    end_date: str | None = None


# --- Роуты ---


@router.get("/projects/{project_id}")
def dashboard(
    project_id: int, db: DbSession, service: CalendarSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд календаря автопостинга (активный план, риски, ближайшие даты, пресеты)."""
    return _run(lambda: service.build_calendar_dashboard(db, project_id))


@router.get("/projects/{project_id}/presets")
def presets(
    project_id: int, db: DbSession, service: CalendarSvc, user: CurrentUser
) -> dict[str, Any]:
    """Готовые варианты календаря с оценкой постов/месяц."""
    return _run(lambda: {"presets": service.build_calendar_presets(db, project_id)})


@router.post("/projects/{project_id}/recommend")
def recommend(
    project_id: int, db: DbSession, service: CalendarSvc, user: CurrentUser
) -> dict[str, Any]:
    """Рекомендовать пресет по медиа/площадкам/балансу/цели."""
    return _run(lambda: service.recommend_calendar(db, project_id))


@router.post("/projects/{project_id}/preview")
def preview(
    project_id: int,
    payload: CalendarPreviewRequest,
    db: DbSession,
    service: CalendarSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Предпросмотр календаря (риски + оценки, без записи)."""
    return _run(
        lambda: service.preview_calendar(
            db, project_id, payload.model_dump(), current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/create-dry-run")
def create_dry_run(
    project_id: int,
    payload: CalendarPreviewRequest,
    db: DbSession,
    service: CalendarSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Проверить создание календаря без записи (dry-run)."""
    return _run(
        lambda: service.create_calendar_plan(
            db, project_id, payload.model_dump(), current_user_id=user.id, dry_run=True
        )
    )


@router.post("/projects/{project_id}/create")
def create(
    project_id: int,
    payload: CalendarPreviewRequest,
    db: DbSession,
    service: CalendarSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать календарь автопостинга (черновик; публикаций нет)."""
    return _run(
        lambda: service.create_calendar_plan(
            db, project_id, payload.model_dump(), current_user_id=user.id, dry_run=False
        )
    )


@router.post("/projects/{project_id}/plans/{calendar_plan_id}/apply")
def apply_plan(
    project_id: int,
    calendar_plan_id: int,
    db: DbSession,
    service: CalendarSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить календарь к автопилоту (создаёт план публикаций; live-флаги не трогает)."""
    return _run(
        lambda: service.apply_calendar_to_project(
            db, project_id, calendar_plan_id, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/plans/{calendar_plan_id}/archive")
def archive_plan(
    project_id: int,
    calendar_plan_id: int,
    db: DbSession,
    service: CalendarSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Архивировать календарь (без удаления)."""
    return _run(
        lambda: service.archive_calendar_plan(
            db, project_id, calendar_plan_id, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/pause")
def pause(
    project_id: int, db: DbSession, service: CalendarSvc, user: CurrentUser
) -> dict[str, Any]:
    """Поставить активный календарь на паузу."""
    return _run(lambda: service.pause_calendar(db, project_id, current_user_id=user.id))


@router.post("/projects/{project_id}/resume")
def resume(
    project_id: int, db: DbSession, service: CalendarSvc, user: CurrentUser
) -> dict[str, Any]:
    """Возобновить приостановленный календарь."""
    return _run(lambda: service.resume_calendar(db, project_id, current_user_id=user.id))
