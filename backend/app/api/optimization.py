"""REST API AI Autonomous Optimization Engine — v0.8.1.

Improvement Item → Optimization Score → Experiment → Measurement → Validation → Learning Update.
Optimization-слой: оценивает, приоритизирует и проверяет улучшения. НЕ применяет улучшения, НЕ
меняет бизнес/KPI/CRM/бюджет, НЕ выполняет задачи, НЕ запускает рекламу/публикации; эксперименты
создаются как ЧЕРНОВИК. Секретов в ответах нет. Все роуты — под tenant-guard.

ВАЖНО (route-коллизии):
- `/experiments/*` занято A/B content-experiments → эксперименты оптимизации namespaced под
  `/optimization-experiments/{id}`;
- UI `/ui/projects/{id}/optimization` занято (оптимизация тем) → UI слоя под `/ai-optimization`.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_optimization_engine_service, get_current_user, get_db
from app.api.security_guards import (
    require_optimization_access,
    require_optimization_experiment_access,
    require_project_access,
)
from app.models.user import User
from app.services.ai_optimization_engine_service import (
    AIOptimizationEngineError,
    AIOptimizationEngineService,
)

router = APIRouter(tags=["optimization"])

DbSession = Annotated[Session, Depends(get_db)]
OptimizationSvc = Annotated[
    AIOptimizationEngineService, Depends(get_ai_optimization_engine_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIOptimizationEngineError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --------------------------------------------------------------------------- #
# Project-scoped                                                              #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/optimization/analyze",
    dependencies=[Depends(require_project_access)],
)
def analyze_optimization(
    project_id: int, db: DbSession, service: OptimizationSvc, user: CurrentUser
) -> dict[str, Any]:
    """Оценить Improvement Backlog → оптимизации → приоритизация (advisory)."""
    return _run(lambda: service.run_optimization_cycle(db, project_id, user_id=user.id))


@router.get("/projects/{project_id}/optimizations", dependencies=[Depends(require_project_access)])
def list_optimizations(
    project_id: int,
    db: DbSession,
    service: OptimizationSvc,
    user: CurrentUser,
    optimization_status: str | None = None,
) -> dict[str, Any]:
    """Ранжированный backlog оптимизаций проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "optimizations": service.get_optimizations(db, project_id, status=optimization_status)
        }
    )


# --------------------------------------------------------------------------- #
# Optimization-scoped                                                         #
# --------------------------------------------------------------------------- #


@router.get("/optimizations/{optimization_id}", dependencies=[Depends(require_optimization_access)])
def get_optimization(
    optimization_id: int, db: DbSession, service: OptimizationSvc, user: CurrentUser
) -> dict[str, Any]:
    """Оптимизация + её эксперименты."""
    return _run(lambda: service.get_optimization_detail(db, optimization_id))


@router.post(
    "/optimizations/{optimization_id}/experiment",
    dependencies=[Depends(require_optimization_access)],
)
def create_experiment(
    optimization_id: int,
    db: DbSession,
    service: OptimizationSvc,
    user: CurrentUser,
    payload: Payload,
) -> dict[str, Any]:
    """Создать эксперимент-гипотезу (status=draft — НЕ запускается автоматически)."""
    return _run(
        lambda: service.create_experiment(
            db,
            optimization_id,
            user_id=user.id,
            title=payload.get("title"),
            hypothesis=payload.get("hypothesis"),
            metric=payload.get("metric"),
            baseline_value=payload.get("baseline_value"),
            target_value=payload.get("target_value"),
            measurement_period=int(payload.get("measurement_period") or 7),
        )
    )


# --------------------------------------------------------------------------- #
# Experiment-scoped (namespaced /optimization-experiments to avoid /experiments clash) #
# --------------------------------------------------------------------------- #


@router.get(
    "/optimization-experiments/{experiment_id}",
    dependencies=[Depends(require_optimization_experiment_access)],
)
def get_experiment(
    experiment_id: int, db: DbSession, service: OptimizationSvc, user: CurrentUser
) -> dict[str, Any]:
    """Эксперимент + его результаты."""
    return _run(lambda: service.get_experiment_detail(db, experiment_id))


@router.post(
    "/optimization-experiments/{experiment_id}/validate",
    dependencies=[Depends(require_optimization_experiment_access)],
)
def validate_experiment(
    experiment_id: int,
    db: DbSession,
    service: OptimizationSvc,
    user: CurrentUser,
    payload: Payload,
) -> dict[str, Any]:
    """Завершить эксперимент замером: measurement → validation → feedback (не применяет)."""
    actual_value = float(payload.get("actual_value") or 0.0)
    return _run(
        lambda: service.validate_experiment(db, experiment_id, actual_value, user_id=user.id)
    )
