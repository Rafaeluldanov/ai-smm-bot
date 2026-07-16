"""REST API AI Business OS MVP Testing Framework — v0.9.0.

DEMO/testing-слой: E2E-прогон всей AI-цепочки. НЕ создаёт реальных пользователей/CRM/платежей, НЕ
выполняет внешних действий, НЕ запускает workflow и не шлёт сообщений. Секретов в ответах нет.
Все роуты требуют авторизации; доступ к demo-ресурсам — только участнику их аккаунта.

ВАЖНО (route-namespace): все роуты под `/demo/*` (свободно; не пересекается с analytics-demo).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_business_os_demo_service,
    get_ai_business_os_report_service,
    get_ai_business_os_scenario_service,
    get_current_user,
    get_db,
)
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import demo_testing_repository as repo
from app.services import saas_security_service as security
from app.services.ai_business_os_demo_service import (
    AIBusinessOSDemoError,
    AIBusinessOSDemoService,
)
from app.services.ai_business_os_report_service import AIBusinessOSReportService
from app.services.ai_business_os_scenario_service import (
    PIPELINE_STAGES,
    AIBusinessOSScenarioService,
)

router = APIRouter(tags=["business-os-testing"])

DbSession = Annotated[Session, Depends(get_db)]
DemoSvc = Annotated[AIBusinessOSDemoService, Depends(get_ai_business_os_demo_service)]
ScenarioSvc = Annotated[AIBusinessOSScenarioService, Depends(get_ai_business_os_scenario_service)]
ReportSvc = Annotated[AIBusinessOSReportService, Depends(get_ai_business_os_report_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIBusinessOSDemoError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _require_account_access(db: Session, user: User, account_id: int | None) -> None:
    """Проверить доступ пользователя к аккаунту demo-ресурса (None — dev/legacy, разрешено)."""
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
# Routes (все под /demo/*)                                                    #
# --------------------------------------------------------------------------- #


@router.post("/demo/workspace/create")
def create_workspace(
    db: DbSession, service: DemoSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Создать demo-воркспейс TEEON под аккаунт (участнику аккаунта)."""
    account_id = payload.get("account_id")
    # account_id обязателен: без него воркспейс был бы «безаккаунтным» (tenant-check fail-open).
    if account_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id обязателен")
    _require_account_access(db, user, int(account_id))
    return _run(
        lambda: service.create_demo_company(
            db, int(account_id), name=str(payload.get("name") or "TEEON Demo"), user_id=user.id
        )
    )


@router.post("/demo/scenario/{scenario_type}/run")
def run_scenario(
    scenario_type: str, db: DbSession, service: ScenarioSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Прогнать demo-сценарий (growth/recovery/optimization) по всей AI-цепочке."""
    workspace_id = payload.get("workspace_id")
    if workspace_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id обязателен"
        )
    _require_workspace(db, user, int(workspace_id))
    return _run(lambda: service.run_scenario(db, int(workspace_id), scenario_type, user_id=user.id))


@router.get("/demo/scenarios")
def list_scenarios(db: DbSession, user: CurrentUser, workspace_id: int) -> dict[str, Any]:
    """Demo-сценарии воркспейса."""
    _require_workspace(db, user, workspace_id)
    return {
        "scenarios": [
            repo.public_scenario_view(s) for s in repo.list_scenarios(db, workspace_id=workspace_id)
        ]
    }


@router.get("/demo/scenario/{scenario_id}/report")
def scenario_report(
    scenario_id: int, db: DbSession, service: ReportSvc, user: CurrentUser
) -> dict[str, Any]:
    """AI Business OS Test Report по прогону сценария."""
    scenario = repo.get_scenario(db, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    _require_workspace(db, user, scenario.workspace_id)
    return _run(lambda: service.generate_report(db, scenario_id, user_id=user.id))


@router.get("/demo/health")
def demo_health(user: CurrentUser, settings: SettingsDep) -> dict[str, Any]:
    """Статус demo-подсистемы: режим, этапы пайплайна, типы сценариев."""
    from app.models.demo_scenario import SCENARIO_TYPES

    return {
        "demo_mode": settings.demo_mode_effective,
        "pipeline_stages": list(PIPELINE_STAGES),
        "scenario_types": list(SCENARIO_TYPES),
        "status": "ok" if settings.demo_mode_effective else "disabled",
    }
