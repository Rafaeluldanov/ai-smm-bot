"""REST API AI Decision Engine — v0.7.4.

Решения → сценарии → оценка → рекомендация → approve → draft. Аналитический/рекомендательный
слой: НЕ применяет решения, НЕ меняет бизнес/CRM/бюджет/live/публикации; apply лишь создаёт
черновик процесса при accepted + APPLY_DECISION. Секретов в ответах нет. Все роуты — под
tenant-guard (project или decision/scenario → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_decision_engine_service, get_current_user, get_db
from app.api.security_guards import (
    require_ai_decision_access,
    require_decision_scenario_access,
    require_project_access,
)
from app.models.user import User
from app.services.ai_decision_engine_service import (
    AIDecisionEngineError,
    AIDecisionEngineService,
)

router = APIRouter(tags=["decisions"])

DbSession = Annotated[Session, Depends(get_db)]
DecisionSvc = Annotated[AIDecisionEngineService, Depends(get_ai_decision_engine_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIDecisionEngineError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class DecisionRequest(BaseModel):
    """Создание AI-решения."""

    decision_type: str
    title: str
    problem_statement: str | None = None
    objective: str | None = None
    priority: str = "medium"
    source_risk_id: int | None = None
    source_action_id: int | None = None
    source_task_id: int | None = None


class ConfirmRequest(BaseModel):
    """Подтверждение применения решения."""

    confirmation: str = ""


# --------------------------------------------------------------------------- #
# Decisions                                                                   #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/ai-decisions", dependencies=[Depends(require_project_access)])
def create_decision(
    project_id: int,
    payload: DecisionRequest,
    db: DbSession,
    service: DecisionSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать решение (из Operations Risk / Business Action / Chief Task / вручную)."""
    return _run(
        lambda: service.create_decision(
            db,
            project_id,
            decision_type=payload.decision_type,
            title=payload.title,
            problem_statement=payload.problem_statement,
            objective=payload.objective,
            priority=payload.priority,
            source_risk_id=payload.source_risk_id,
            source_action_id=payload.source_action_id,
            source_task_id=payload.source_task_id,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/ai-decisions", dependencies=[Depends(require_project_access)])
def list_decisions(
    project_id: int,
    db: DbSession,
    service: DecisionSvc,
    user: CurrentUser,
    decision_status: str | None = None,
) -> dict[str, Any]:
    """Список решений проекта (опционально по статусу)."""
    return _run(
        lambda: {"decisions": service.list_decisions(db, project_id, status=decision_status)}
    )


@router.get("/ai-decisions/{decision_id}", dependencies=[Depends(require_ai_decision_access)])
def get_decision(
    decision_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Решение + сценарии + сигналы."""
    return _run(lambda: service.get_decision(db, decision_id))


@router.post(
    "/ai-decisions/{decision_id}/analyze",
    dependencies=[Depends(require_ai_decision_access)],
)
def analyze_decision(
    decision_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Проанализировать: сигналы → сценарии → оценка → рекомендация (advisory)."""
    return _run(lambda: service.analyze_decision(db, decision_id, user_id=user.id))


@router.get(
    "/ai-decisions/{decision_id}/scenarios",
    dependencies=[Depends(require_ai_decision_access)],
)
def list_scenarios(
    decision_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сценарии (варианты решения) с оценками."""
    return _run(lambda: {"scenarios": service.get_decision(db, decision_id)["scenarios"]})


@router.get(
    "/ai-decisions/{decision_id}/explanation", dependencies=[Depends(require_ai_decision_access)]
)
def decision_explanation(
    decision_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение владельцу: почему AI выбрал этот путь."""
    return _run(lambda: service.explain_decision(db, decision_id))


@router.post(
    "/ai-decisions/{decision_id}/accept",
    dependencies=[Depends(require_ai_decision_access)],
)
def accept_decision(
    decision_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить решение (status=accepted). НЕ выполняет."""
    return _run(lambda: service.accept_decision(db, decision_id, user_id=user.id))


@router.post(
    "/ai-decisions/{decision_id}/apply",
    dependencies=[Depends(require_ai_decision_access)],
)
def apply_decision(
    decision_id: int,
    payload: ConfirmRequest,
    db: DbSession,
    service: DecisionSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить решение (accepted + confirmation APPLY_DECISION → черновик процесса). Live off."""
    return _run(
        lambda: service.apply_decision(
            db, decision_id, confirmation=payload.confirmation, user_id=user.id
        )
    )


# --------------------------------------------------------------------------- #
# Scenarios                                                                   #
# --------------------------------------------------------------------------- #


@router.post(
    "/scenarios/{scenario_id}/select",
    dependencies=[Depends(require_decision_scenario_access)],
)
def select_scenario(
    scenario_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Выбрать сценарий владельцем (status=selected)."""
    return _run(lambda: service.select_scenario(db, scenario_id, user_id=user.id))


@router.post(
    "/scenarios/{scenario_id}/reject",
    dependencies=[Depends(require_decision_scenario_access)],
)
def reject_scenario(
    scenario_id: int, db: DbSession, service: DecisionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить сценарий (status=rejected)."""
    return _run(lambda: service.reject_scenario(db, scenario_id, user_id=user.id))
