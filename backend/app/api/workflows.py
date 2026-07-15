"""REST API AI Workflow Manager / Business Execution Layer — v0.7.2.

Управление бизнес-процессами: процессы, этапы (assign/status/complete), блокеры и health.
Workflow management слой: НЕ выполняет задачи, НЕ меняет CRM/бюджет/продажи/live/публикации.
Секретов в ответах нет. Все роуты — под tenant-guard (project или workflow/step/blocker → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_ai_workflow_manager_service, get_current_user, get_db
from app.api.security_guards import (
    require_project_access,
    require_workflow_access,
    require_workflow_blocker_access,
    require_workflow_step_access,
)
from app.models.user import User
from app.services.ai_workflow_manager_service import (
    AIWorkflowManagerError,
    AIWorkflowManagerService,
)

router = APIRouter(tags=["workflows"])

DbSession = Annotated[Session, Depends(get_db)]
WorkflowSvc = Annotated[AIWorkflowManagerService, Depends(get_ai_workflow_manager_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIWorkflowManagerError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class WorkflowRequest(BaseModel):
    """Создание процесса из цели/задачи."""

    name: str = ""
    workflow_type: str
    goal: str | None = None
    description: str | None = None
    target_value: float = 0.0
    status: str = "draft"
    objective_id: int | None = None
    task_id: int | None = None


class AssignRequest(BaseModel):
    """Назначение ответственного за этап."""

    owner_user_id: int | None = None


class StatusRequest(BaseModel):
    """Смена статуса этапа."""

    status: str
    progress_percent: float | None = None


class BlockerRequest(BaseModel):
    """Создание блокера процесса."""

    blocker_type: str
    title: str = Field(max_length=255)
    step_id: int | None = None
    description: str | None = None
    severity: str = "medium"


# --------------------------------------------------------------------------- #
# Workflows                                                                   #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/workflows", dependencies=[Depends(require_project_access)])
def create_workflow(
    project_id: int,
    payload: WorkflowRequest,
    db: DbSession,
    service: WorkflowSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать бизнес-процесс из цели (Business OS) или AI-задачи (Chief of Staff)."""
    return _run(
        lambda: service.create_workflow_from_goal(
            db,
            project_id,
            name=payload.name,
            workflow_type=payload.workflow_type,
            goal=payload.goal,
            description=payload.description,
            target_value=payload.target_value,
            objective_id=payload.objective_id,
            task_id=payload.task_id,
            status=payload.status,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/workflows", dependencies=[Depends(require_project_access)])
def list_workflows(
    project_id: int,
    db: DbSession,
    service: WorkflowSvc,
    user: CurrentUser,
    workflow_status: str | None = None,
) -> dict[str, Any]:
    """Список процессов проекта (опционально по статусу)."""
    return _run(
        lambda: {"workflows": service.list_workflows(db, project_id, status=workflow_status)}
    )


@router.get("/workflows/{workflow_id}", dependencies=[Depends(require_workflow_access)])
def get_workflow(
    workflow_id: int, db: DbSession, service: WorkflowSvc, user: CurrentUser
) -> dict[str, Any]:
    """Процесс + этапы + блокеры (с актуальным прогрессом)."""
    return _run(lambda: service.get_workflow(db, workflow_id))


@router.post(
    "/workflows/{workflow_id}/generate-steps", dependencies=[Depends(require_workflow_access)]
)
def generate_steps(
    workflow_id: int, db: DbSession, service: WorkflowSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сгенерировать этапы процесса (Executive Plan + Chief Tasks + дефолт по типу)."""
    return _run(
        lambda: {"steps": service.generate_workflow_steps(db, workflow_id, user_id=user.id)}
    )


@router.get("/workflows/{workflow_id}/steps", dependencies=[Depends(require_workflow_access)])
def list_steps(
    workflow_id: int, db: DbSession, service: WorkflowSvc, user: CurrentUser
) -> dict[str, Any]:
    """Этапы процесса по порядку."""
    return _run(lambda: {"steps": service.list_steps(db, workflow_id)})


@router.get("/workflows/{workflow_id}/health", dependencies=[Depends(require_workflow_access)])
def workflow_health(
    workflow_id: int, db: DbSession, service: WorkflowSvc, user: CurrentUser
) -> dict[str, Any]:
    """Health процесса: просрочки, блокеры, отсутствие движения, риски, рекомендации."""
    return _run(lambda: service.analyze_workflow_health(db, workflow_id))


@router.post("/workflows/{workflow_id}/blockers", dependencies=[Depends(require_workflow_access)])
def create_blocker(
    workflow_id: int,
    payload: BlockerRequest,
    db: DbSession,
    service: WorkflowSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать блокер процесса (помечает связанный этап blocked)."""
    return _run(
        lambda: service.create_blocker(
            db,
            workflow_id,
            blocker_type=payload.blocker_type,
            title=payload.title,
            step_id=payload.step_id,
            description=payload.description,
            severity=payload.severity,
            user_id=user.id,
        )
    )


# --------------------------------------------------------------------------- #
# Steps                                                                       #
# --------------------------------------------------------------------------- #


@router.post("/steps/{step_id}/assign", dependencies=[Depends(require_workflow_step_access)])
def assign_step(
    step_id: int,
    payload: AssignRequest,
    db: DbSession,
    service: WorkflowSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Назначить ответственного за этап. НЕ выполняет этап."""
    return _run(lambda: service.assign_step(db, step_id, payload.owner_user_id, user_id=user.id))


@router.post("/steps/{step_id}/status", dependencies=[Depends(require_workflow_step_access)])
def update_step_status(
    step_id: int,
    payload: StatusRequest,
    db: DbSession,
    service: WorkflowSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Сменить статус этапа (complete лишь фиксирует статус). НЕ запускает внешних действий."""
    return _run(
        lambda: service.update_step_status(
            db, step_id, payload.status, progress_percent=payload.progress_percent, user_id=user.id
        )
    )


# --------------------------------------------------------------------------- #
# Blockers                                                                     #
# --------------------------------------------------------------------------- #


@router.post(
    "/blockers/{blocker_id}/resolve",
    dependencies=[Depends(require_workflow_blocker_access)],
)
def resolve_blocker(
    blocker_id: int, db: DbSession, service: WorkflowSvc, user: CurrentUser
) -> dict[str, Any]:
    """Снять блокер (status=resolved). Возвращает связанный blocked-этап в работу."""
    return _run(lambda: service.resolve_blocker(db, blocker_id, user_id=user.id))
