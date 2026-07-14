"""REST API мониторинга live-автопилота и kill switch — v0.6.1.

Клиентский слой «как себя чувствует автопилот»: дашборд здоровья, снимки, инциденты (подтвердить/
решить/игнорировать), стоп-кран (пауза/возобновление проекта и площадок), превью авто-паузы. Всё под
project-гардом (инциденты — под incident-гардом через их проект). Секретов/токенов в ответах нет;
API НЕ включает и НЕ обходит глобальные live-флаги; «resume» не перевзводит реальную публикацию.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_db,
    get_live_autopilot_monitoring_service,
)
from app.api.security_guards import require_live_incident_access, require_project_access
from app.models.user import User
from app.services.live_autopilot_monitoring_service import (
    LiveAutopilotMonitoringError,
    LiveAutopilotMonitoringService,
)
from app.services.live_readiness_service import LiveReadinessError

router = APIRouter(prefix="/live-autopilot-monitoring", tags=["live-autopilot-monitoring"])

DbSession = Annotated[Session, Depends(get_db)]
MonitoringSvc = Annotated[
    LiveAutopilotMonitoringService, Depends(get_live_autopilot_monitoring_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    # Kill-switch resume делегирует в LiveReadinessService, который бросает СВОЙ LiveReadinessError
    # (неверное подтверждение / площадка не готова) — маппим его так же, чтобы не отдавать 500.
    try:
        return action()
    except (LiveAutopilotMonitoringError, LiveReadinessError) as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class HealthCheckRequest(BaseModel):
    """Параметры проверки здоровья (dry_run=None → значение из настроек)."""

    dry_run: bool | None = None


class ConfirmationRequest(BaseModel):
    """Подтверждение стоп-крана/возобновления (текст-подтверждение)."""

    confirmation: str = ""


# --------------------------------------------------------------------------- #
# Дашборд / снимки / здоровье                                                 #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд мониторинга автопилота (здоровье, инциденты, стоп-кран)."""
    return _run(lambda: service.build_dashboard(db, project_id))


@router.get("/projects/{project_id}/snapshots", dependencies=[Depends(require_project_access)])
def list_snapshots(
    project_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser, limit: int = 50
) -> dict[str, Any]:
    """Список снимков мониторинга проекта."""
    return _run(lambda: service.list_snapshots(db, project_id, limit=limit))


@router.post("/projects/{project_id}/health-check", dependencies=[Depends(require_project_access)])
def run_health_check(
    project_id: int,
    payload: HealthCheckRequest,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Запустить проверку здоровья (dry-run по умолчанию из настроек)."""
    return _run(
        lambda: service.run_health_check(
            db, project_id, current_user_id=user.id, dry_run=payload.dry_run
        )
    )


@router.get(
    "/projects/{project_id}/auto-pause/preview", dependencies=[Depends(require_project_access)]
)
def auto_pause_preview(
    project_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Показать, сработала бы авто-пауза (без действия)."""
    return _run(lambda: service.preview_auto_pause(db, project_id))


# --------------------------------------------------------------------------- #
# Инциденты                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/incidents", dependencies=[Depends(require_project_access)])
def list_incidents(
    project_id: int,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
    status_filter: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Список инцидентов проекта (опциональный фильтр ?status_filter=open)."""
    return _run(lambda: service.list_incidents(db, project_id, status=status_filter, limit=limit))


@router.get("/incidents/{incident_id}", dependencies=[Depends(require_live_incident_access)])
def incident_detail(
    incident_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Детали инцидента (доступ проверяется через incident.project_id)."""
    return _run(lambda: service.get_incident(db, incident_id))


@router.post(
    "/incidents/{incident_id}/acknowledge",
    dependencies=[Depends(require_live_incident_access)],
)
def acknowledge_incident(
    incident_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Подтвердить инцидент."""
    return _run(lambda: service.acknowledge_incident(db, incident_id, current_user_id=user.id))


@router.post(
    "/incidents/{incident_id}/resolve", dependencies=[Depends(require_live_incident_access)]
)
def resolve_incident(
    incident_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отметить инцидент решённым."""
    return _run(lambda: service.resolve_incident(db, incident_id, current_user_id=user.id))


@router.post(
    "/incidents/{incident_id}/ignore", dependencies=[Depends(require_live_incident_access)]
)
def ignore_incident(
    incident_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отметить инцидент проигнорированным."""
    return _run(lambda: service.ignore_incident(db, incident_id, current_user_id=user.id))


# --------------------------------------------------------------------------- #
# Kill switch: пауза / возобновление                                          #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/pause-preview", dependencies=[Depends(require_project_access)])
def pause_preview(
    project_id: int, db: DbSession, service: MonitoringSvc, user: CurrentUser
) -> dict[str, Any]:
    """Предпросмотр стоп-крана (не ставит паузу): что затронет и какое подтверждение нужно."""
    return _run(lambda: service.preview_pause(db, project_id))


@router.post("/projects/{project_id}/pause", dependencies=[Depends(require_project_access)])
def pause_project(
    project_id: int,
    payload: ConfirmationRequest,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Остановить автопилот проекта (пауза + выключение live). Требует подтверждения."""
    return _run(
        lambda: service.pause_project_autopilot(
            db, project_id, confirmation=payload.confirmation, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/resume", dependencies=[Depends(require_project_access)])
def resume_project(
    project_id: int,
    payload: ConfirmationRequest,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Возобновить автопилот проекта (черновики). Реальную публикацию НЕ перевзводит."""
    return _run(
        lambda: service.resume_project_autopilot(
            db, project_id, confirmation=payload.confirmation, current_user_id=user.id
        )
    )


@router.post(
    "/projects/{project_id}/platforms/{platform_key}/pause",
    dependencies=[Depends(require_project_access)],
)
def pause_platform(
    project_id: int,
    platform_key: str,
    payload: ConfirmationRequest,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Выключить live для площадки (черновики продолжаются). Требует подтверждения."""
    return _run(
        lambda: service.pause_platform_live(
            db, project_id, platform_key, confirmation=payload.confirmation, current_user_id=user.id
        )
    )


@router.post(
    "/projects/{project_id}/platforms/{platform_key}/resume",
    dependencies=[Depends(require_project_access)],
)
def resume_platform(
    project_id: int,
    platform_key: str,
    payload: ConfirmationRequest,
    db: DbSession,
    service: MonitoringSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Возобновить live для площадки — через готовность (подтверждение + проверка)."""
    return _run(
        lambda: service.resume_platform_live(
            db, project_id, platform_key, payload.confirmation, current_user_id=user.id
        )
    )
