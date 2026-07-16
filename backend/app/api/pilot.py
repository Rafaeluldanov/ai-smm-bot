"""REST API AI Business OS Pilot — v0.9.1.

PILOT/launch-слой: окружение первого реального бизнес-пилота. Всё advisory: НЕ меняет бизнес/CRM, НЕ
выполняет workflow, НЕ шлёт сообщений, НЕ ходит во внешние API, НЕ создаёт платежей. Секретов в
ответах нет. Все роуты требуют авторизации; доступ к pilot-ресурсам — только участнику аккаунта;
при pilot_mode=false pilot-действия запрещены (403).

ВАЖНО (route-namespace): все роуты под `/pilot/*` (свободно).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_business_pilot_report_service,
    get_ai_business_pilot_scenario_service,
    get_ai_business_pilot_service,
    get_ai_ceo_dashboard_service,
    get_current_user,
    get_db,
)
from app.models.user import User
from app.repositories import pilot_repository as repo
from app.services import saas_security_service as security
from app.services.ai_business_pilot_report_service import AIBusinessPilotReportService
from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    AIBusinessPilotService,
    PilotModeDisabledError,
)
from app.services.ai_ceo_dashboard_service import AICEODashboardService

router = APIRouter(tags=["pilot"])

DbSession = Annotated[Session, Depends(get_db)]
PilotSvc = Annotated[AIBusinessPilotService, Depends(get_ai_business_pilot_service)]
ScenarioSvc = Annotated[
    AIBusinessPilotScenarioService, Depends(get_ai_business_pilot_scenario_service)
]
DashboardSvc = Annotated[AICEODashboardService, Depends(get_ai_ceo_dashboard_service)]
ReportSvc = Annotated[AIBusinessPilotReportService, Depends(get_ai_business_pilot_report_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except PilotModeDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AIBusinessPilotError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _require_account_access(db: Session, user: User, account_id: int | None) -> None:
    """Доступ пользователя к аккаунту pilot-ресурса (None — dev/legacy, разрешено)."""
    if account_id is None:
        return
    if not security.user_can_access_account(db, user, account_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")


def _require_workspace(db: Session, user: User, workspace_id: int) -> Any:
    workspace = repo.get_workspace(db, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    _require_account_access(db, user, workspace.account_id)
    return workspace


# --------------------------------------------------------------------------- #
# Routes (все под /pilot/*)                                                   #
# --------------------------------------------------------------------------- #


@router.post("/pilot/workspaces")
def create_workspace(
    db: DbSession, service: PilotSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Создать pilot-воркспейс (участнику аккаунта)."""
    account_id = payload.get("account_id")
    if account_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id обязателен")
    _require_account_access(db, user, int(account_id))
    return _run(
        lambda: service.create_pilot_workspace(
            db,
            int(account_id),
            company_name=str(payload.get("company_name") or "Pilot Company"),
            industry=str(payload.get("industry") or ""),
            user_id=user.id,
        )
    )


@router.get("/pilot/workspaces")
def list_workspaces(
    db: DbSession, service: PilotSvc, user: CurrentUser, account_id: int
) -> dict[str, Any]:
    """Pilot-воркспейсы аккаунта."""
    _require_account_access(db, user, account_id)
    return _run(lambda: {"workspaces": service.list_workspaces(db, account_id=account_id)})


@router.post("/pilot/workspaces/{workspace_id}/profile")
def create_profile(
    workspace_id: int, db: DbSession, service: PilotSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Создать бизнес-профиль пилота."""
    _require_workspace(db, user, workspace_id)
    return _run(
        lambda: service.create_business_profile(
            db,
            workspace_id,
            products=payload.get("products"),
            services=payload.get("services"),
            team=payload.get("team"),
            sales_channels=payload.get("sales_channels"),
            business_description=payload.get("business_description"),
            current_revenue=float(payload.get("current_revenue") or 0.0),
            target_revenue=float(payload.get("target_revenue") or 0.0),
            kpi=payload.get("kpi"),
            user_id=user.id,
        )
    )


@router.get("/pilot/workspaces/{workspace_id}/health")
def workspace_health(
    workspace_id: int, db: DbSession, service: PilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Здоровье бизнеса пилота (read-only)."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.get_business_health(db, workspace_id))


@router.post("/pilot/workspaces/{workspace_id}/run")
def run_pilot(
    workspace_id: int, db: DbSession, service: ScenarioSvc, user: CurrentUser
) -> dict[str, Any]:
    """Прогнать growth-пилот по всей AI-цепочке (advisory)."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.run_growth_pilot(db, workspace_id, user_id=user.id))


@router.get("/pilot/workspaces/{workspace_id}/dashboard")
def workspace_dashboard(
    workspace_id: int, db: DbSession, service: DashboardSvc, user: CurrentUser
) -> dict[str, Any]:
    """CEO Dashboard (business command center)."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.generate_dashboard(db, workspace_id, user_id=user.id))


@router.get("/pilot/workspaces/{workspace_id}/report")
def workspace_report(
    workspace_id: int, db: DbSession, service: ReportSvc, user: CurrentUser
) -> dict[str, Any]:
    """AI Business Pilot Report."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.generate_pilot_report(db, workspace_id, user_id=user.id))
