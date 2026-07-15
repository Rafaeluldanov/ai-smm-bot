"""REST API AI Strategy Simulator — v0.7.5.

Decision Scenario → Simulation → Forecast → Comparison → Recommendation. Аналитический слой:
моделирует последствия сценария на 30/60/90 дней. НЕ гарантирует прибыль, НЕ меняет
бизнес/CRM/бюджет/live/публикации/рекламу, НЕ выполняет стратегии. Секретов в ответах нет.
Все роуты — под tenant-guard (project / simulation / decision → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_strategy_simulator_service, get_current_user, get_db
from app.api.security_guards import (
    require_ai_decision_access,
    require_project_access,
    require_simulation_access,
)
from app.models.user import User
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    AIStrategySimulatorService,
)

router = APIRouter(tags=["strategy-simulator"])

DbSession = Annotated[Session, Depends(get_db)]
SimulatorSvc = Annotated[AIStrategySimulatorService, Depends(get_ai_strategy_simulator_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIStrategySimulatorError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class SimulationRequest(BaseModel):
    """Создание стратегической симуляции из сценария решения."""

    scenario_id: int
    title: str | None = None
    objective: str | None = None
    simulation_period: str = "90_days"


# --------------------------------------------------------------------------- #
# Simulations                                                                 #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/simulations", dependencies=[Depends(require_project_access)])
def create_simulation(
    project_id: int,
    payload: SimulationRequest,
    db: DbSession,
    service: SimulatorSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать симуляцию из сценария решения. НЕ запускает моделирование (advisory)."""
    return _run(
        lambda: service.create_simulation(
            db,
            project_id,
            scenario_id=payload.scenario_id,
            title=payload.title,
            objective=payload.objective,
            simulation_period=payload.simulation_period,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/simulations", dependencies=[Depends(require_project_access)])
def list_simulations(
    project_id: int,
    db: DbSession,
    service: SimulatorSvc,
    user: CurrentUser,
    simulation_status: str | None = None,
) -> dict[str, Any]:
    """Список симуляций проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "simulations": service.list_simulations(db, project_id, status=simulation_status),
            "summary": service.get_summary(db, project_id),
        }
    )


@router.get("/simulations/{simulation_id}", dependencies=[Depends(require_simulation_access)])
def get_simulation(
    simulation_id: int, db: DbSession, service: SimulatorSvc, user: CurrentUser
) -> dict[str, Any]:
    """Симуляция + прогнозы."""
    return _run(lambda: service.get_simulation(db, simulation_id))


@router.post("/simulations/{simulation_id}/run", dependencies=[Depends(require_simulation_access)])
def run_simulation(
    simulation_id: int, db: DbSession, service: SimulatorSvc, user: CurrentUser
) -> dict[str, Any]:
    """Запустить моделирование: baseline → прогноз на 30/60/90 дней → уверенность (advisory)."""
    return _run(lambda: service.simulate_scenario(db, simulation_id, user_id=user.id))


@router.get(
    "/simulations/{simulation_id}/forecast", dependencies=[Depends(require_simulation_access)]
)
def get_forecast(
    simulation_id: int, db: DbSession, service: SimulatorSvc, user: CurrentUser
) -> dict[str, Any]:
    """Прогнозы симуляции + объяснение."""
    return _run(
        lambda: {
            "forecast": service.get_forecast(db, simulation_id),
            "explanation": service.explain_forecast(db, simulation_id),
        }
    )


# --------------------------------------------------------------------------- #
# Comparison / Recommendation (по решению Decision Engine)                    #
# --------------------------------------------------------------------------- #


@router.post(
    "/decisions/{decision_id}/compare-scenarios",
    dependencies=[Depends(require_ai_decision_access)],
)
def compare_scenarios(
    decision_id: int, db: DbSession, service: SimulatorSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сравнить сценарии решения по Strategy Score = Impact × Confidence − Risk (advisory)."""
    return _run(lambda: service.compare_scenarios(db, decision_id, user_id=user.id))


@router.get(
    "/decisions/{decision_id}/strategy-recommendation",
    dependencies=[Depends(require_ai_decision_access)],
)
def strategy_recommendation(
    decision_id: int, db: DbSession, service: SimulatorSvc, user: CurrentUser
) -> dict[str, Any]:
    """Рекомендация стратегии: {winner, confidence, reason}. Только совет, НЕ выполнение."""
    return _run(lambda: service.recommend_strategy(db, decision_id, user_id=user.id))
