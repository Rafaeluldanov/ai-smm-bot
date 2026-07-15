"""REST API AI Business Planner — v0.7.7.

Business Goal → Gap Analysis → Strategic Plan → Quarter Objectives → KPI → Milestones → Workflow
Draft. Planning-слой: превращает цель в план. НЕ выполняет план, НЕ меняет бизнес/CRM/бюджет, НЕ
запускает рекламу/публикации; approve меняет лишь статус, convert (только при approved +
подтверждении) создаёт ЧЕРНОВИК процесса. Секретов в ответах нет. Все роуты — под tenant-guard
(project / goal / plan → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_business_planner_service, get_current_user, get_db
from app.api.security_guards import (
    require_goal_access,
    require_plan_access,
    require_project_access,
)
from app.models.user import User
from app.services.ai_business_planner_service import (
    AIBusinessPlannerError,
    AIBusinessPlannerService,
)

router = APIRouter(tags=["business-planner"])

DbSession = Annotated[Session, Depends(get_db)]
PlannerSvc = Annotated[AIBusinessPlannerService, Depends(get_ai_business_planner_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIBusinessPlannerError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class GoalRequest(BaseModel):
    """Создание бизнес-цели."""

    goal_type: str
    title: str
    description: str | None = None
    target_value: float = 0.0
    current_value: float = 0.0


class ConfirmRequest(BaseModel):
    """Подтверждение конвертации плана в черновик процесса."""

    confirmation: str = ""


# --------------------------------------------------------------------------- #
# Goals                                                                       #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/goals", dependencies=[Depends(require_project_access)])
def create_goal(
    project_id: int,
    payload: GoalRequest,
    db: DbSession,
    service: PlannerSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать бизнес-цель владельца."""
    return _run(
        lambda: service.create_business_goal(
            db,
            project_id,
            goal_type=payload.goal_type,
            title=payload.title,
            description=payload.description,
            target_value=payload.target_value,
            current_value=payload.current_value,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/goals", dependencies=[Depends(require_project_access)])
def list_goals(
    project_id: int,
    db: DbSession,
    service: PlannerSvc,
    user: CurrentUser,
    goal_status: str | None = None,
) -> dict[str, Any]:
    """Список целей проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "goals": service.list_goals(db, project_id, status=goal_status),
            "summary": service.get_summary(db, project_id),
        }
    )


@router.get("/goals/{goal_id}", dependencies=[Depends(require_goal_access)])
def get_goal(goal_id: int, db: DbSession, service: PlannerSvc, user: CurrentUser) -> dict[str, Any]:
    """Цель + gap + планы."""
    return _run(
        lambda: {
            **service.get_goal(db, goal_id),
            "gap": service.analyze_gap(db, goal_id),
        }
    )


@router.post("/goals/{goal_id}/plan", dependencies=[Depends(require_goal_access)])
def generate_plan(
    goal_id: int, db: DbSession, service: PlannerSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сгенерировать стратегический план: gap → стратегия → кварталы → KPI → вехи (advisory)."""
    return _run(lambda: service.generate_strategic_plan(db, goal_id, user_id=user.id))


# --------------------------------------------------------------------------- #
# Plans                                                                       #
# --------------------------------------------------------------------------- #


@router.get("/plans/{plan_id}", dependencies=[Depends(require_plan_access)])
def get_plan(plan_id: int, db: DbSession, service: PlannerSvc, user: CurrentUser) -> dict[str, Any]:
    """План + квартальные цели + вехи + объяснение."""
    return _run(
        lambda: {
            **service.get_plan(db, plan_id),
            "explanation": service.explain_plan(db, plan_id),
        }
    )


@router.get("/plans/{plan_id}/objectives", dependencies=[Depends(require_plan_access)])
def get_objectives(
    plan_id: int, db: DbSession, service: PlannerSvc, user: CurrentUser
) -> dict[str, Any]:
    """Квартальные цели плана (+ вехи)."""
    return _run(lambda: {"objectives": service.get_objectives(db, plan_id)})


@router.post("/plans/{plan_id}/approve", dependencies=[Depends(require_plan_access)])
def approve_plan(
    plan_id: int, db: DbSession, service: PlannerSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить план (status=approved). НЕ выполняет."""
    return _run(lambda: service.approve_plan(db, plan_id, user_id=user.id))


@router.post("/plans/{plan_id}/convert-workflow", dependencies=[Depends(require_plan_access)])
def convert_workflow(
    plan_id: int,
    payload: ConfirmRequest,
    db: DbSession,
    service: PlannerSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать ЧЕРНОВИК процесса из плана (approved + confirmation CONVERT_PLAN). Live off."""
    return _run(
        lambda: service.convert_to_workflow(
            db, plan_id, confirmation=payload.confirmation, user_id=user.id
        )
    )
