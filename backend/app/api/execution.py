"""REST API AI Execution Coordinator — v0.7.8.

Approved Strategic Plan → Execution Plan → Objectives → Tasks → Owners → Progress → AI
Coordination. Coordination-слой: управляет исполнением плана. НЕ выполняет задачи, НЕ меняет
бизнес/CRM/бюджет, НЕ запускает рекламу/публикации; assign/status/complete меняют лишь статус.
Секретов в ответах нет. Все роуты — под tenant-guard (project / plan / task → project).

ВАЖНО (route-коллизия): задачи вынесены под `/execution-tasks/{id}` — `/tasks/{id}/assign` уже
занят media-curation review, а `/tasks/{id}` — Chief of Staff / media-curation.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_execution_coordinator_service, get_current_user, get_db
from app.api.security_guards import (
    require_execution_plan_access,
    require_execution_task_access,
    require_project_access,
)
from app.models.user import User
from app.services.ai_execution_coordinator_service import (
    AIExecutionCoordinatorError,
    AIExecutionCoordinatorService,
)

router = APIRouter(tags=["execution"])

DbSession = Annotated[Session, Depends(get_db)]
ExecutionSvc = Annotated[
    AIExecutionCoordinatorService, Depends(get_ai_execution_coordinator_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIExecutionCoordinatorError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ExecutionPlanRequest(BaseModel):
    """Создание плана исполнения из утверждённого стратегического плана."""

    strategic_plan_id: int
    title: str | None = None
    description: str | None = None


class AssignRequest(BaseModel):
    """Назначение владельца задачи."""

    owner_user_id: int


class StatusRequest(BaseModel):
    """Смена статуса задачи."""

    status: str


# --------------------------------------------------------------------------- #
# Execution plans                                                             #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/execution-plans", dependencies=[Depends(require_project_access)]
)
def create_execution_plan(
    project_id: int,
    payload: ExecutionPlanRequest,
    db: DbSession,
    service: ExecutionSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать план исполнения из УТВЕРЖДЁННОГО стратегического плана. НЕ запускает генерацию."""
    return _run(
        lambda: service.create_execution_plan(
            db,
            project_id,
            strategic_plan_id=payload.strategic_plan_id,
            title=payload.title,
            description=payload.description,
            user_id=user.id,
        )
    )


@router.get(
    "/projects/{project_id}/execution-plans", dependencies=[Depends(require_project_access)]
)
def list_execution_plans(
    project_id: int,
    db: DbSession,
    service: ExecutionSvc,
    user: CurrentUser,
    plan_status: str | None = None,
) -> dict[str, Any]:
    """Список планов исполнения проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "execution_plans": service.list_execution_plans(db, project_id, status=plan_status),
            "summary": service.get_summary(db, project_id),
        }
    )


@router.get(
    "/execution-plans/{execution_plan_id}",
    dependencies=[Depends(require_execution_plan_access)],
)
def get_execution_plan(
    execution_plan_id: int, db: DbSession, service: ExecutionSvc, user: CurrentUser
) -> dict[str, Any]:
    """План исполнения + цели + задачи."""
    return _run(lambda: service.get_execution_plan(db, execution_plan_id))


@router.post(
    "/execution-plans/{execution_plan_id}/generate",
    dependencies=[Depends(require_execution_plan_access)],
)
def generate_execution(
    execution_plan_id: int, db: DbSession, service: ExecutionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сгенерировать исполнение: цели → задачи → прогресс (advisory). НЕ выполняет задачи."""
    return _run(lambda: service.generate_execution(db, execution_plan_id, user_id=user.id))


@router.get(
    "/execution-plans/{execution_plan_id}/tasks",
    dependencies=[Depends(require_execution_plan_access)],
)
def get_tasks(
    execution_plan_id: int, db: DbSession, service: ExecutionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Все задачи плана исполнения."""
    return _run(lambda: {"tasks": service.get_tasks(db, execution_plan_id)})


@router.get(
    "/execution-plans/{execution_plan_id}/health",
    dependencies=[Depends(require_execution_plan_access)],
)
def get_health(
    execution_plan_id: int, db: DbSession, service: ExecutionSvc, user: CurrentUser
) -> dict[str, Any]:
    """Здоровье исполнения: прогресс + блокеры + AI-рекомендации."""
    return _run(lambda: service.get_health(db, execution_plan_id))


# --------------------------------------------------------------------------- #
# Tasks (namespaced /execution-tasks to avoid /tasks collision)               #
# --------------------------------------------------------------------------- #


@router.post(
    "/execution-tasks/{task_id}/assign",
    dependencies=[Depends(require_execution_task_access)],
)
def assign_task(
    task_id: int,
    payload: AssignRequest,
    db: DbSession,
    service: ExecutionSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Назначить владельца задачи (только owner + status). НЕ выполняет."""
    return _run(lambda: service.assign_owner(db, task_id, payload.owner_user_id, user_id=user.id))


@router.post(
    "/execution-tasks/{task_id}/status",
    dependencies=[Depends(require_execution_task_access)],
)
def set_task_status(
    task_id: int,
    payload: StatusRequest,
    db: DbSession,
    service: ExecutionSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Сменить статус задачи (только статус). НЕ запускает действий."""
    return _run(lambda: service.set_task_status(db, task_id, payload.status, user_id=user.id))
