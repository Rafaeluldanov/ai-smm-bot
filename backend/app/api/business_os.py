"""REST API Autonomous Business OS / AI Executive Layer — v0.7.0.

Верхний слой управления: бизнес-цели, исполнительный анализ+план, приоритизированные
бизнес-действия, review (accept/reject) и apply с подтверждением, объяснение.

Advisory + planning слой: НЕ меняет бизнес/CRM/бюджет/live/публикации сам. apply меняет
лишь draft-стратегию/кампанию при status=accepted И confirmation=APPLY_BUSINESS_ACTION.
Секретов в ответах нет. Все роуты — под tenant-guard (project или action → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_executive_service, get_current_user, get_db
from app.api.security_guards import require_action_access, require_project_access
from app.models.user import User
from app.services.ai_executive_service import AIExecutiveError, AIExecutiveService

router = APIRouter(tags=["business-os"])

DbSession = Annotated[Session, Depends(get_db)]
ExecSvc = Annotated[AIExecutiveService, Depends(get_ai_executive_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIExecutiveError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ObjectiveRequest(BaseModel):
    """Создание бизнес-цели."""

    type: str
    title: str
    description: str | None = None
    target_value: float = 0.0
    current_value: float = 0.0
    unit: str | None = None


class AnalyzeRequest(BaseModel):
    """Запуск исполнительного анализа (опционально под конкретную цель)."""

    objective_id: int | None = None


class ConfirmRequest(BaseModel):
    """Подтверждение применения бизнес-действия."""

    confirmation: str = ""


# --------------------------------------------------------------------------- #
# Objectives                                                                  #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/objectives", dependencies=[Depends(require_project_access)])
def create_objective(
    project_id: int,
    payload: ObjectiveRequest,
    db: DbSession,
    service: ExecSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать бизнес-цель (status=draft)."""
    return _run(
        lambda: service.create_objective(
            db,
            project_id,
            type=payload.type,
            title=payload.title,
            description=payload.description,
            target_value=payload.target_value,
            current_value=payload.current_value,
            unit=payload.unit,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/objectives", dependencies=[Depends(require_project_access)])
def list_objectives(
    project_id: int, db: DbSession, service: ExecSvc, user: CurrentUser
) -> dict[str, Any]:
    """Список бизнес-целей проекта."""
    return _run(lambda: {"objectives": service.list_objectives(db, project_id)})


# --------------------------------------------------------------------------- #
# Executive analysis & plan                                                   #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/executive/analyze", dependencies=[Depends(require_project_access)]
)
def analyze(
    project_id: int,
    payload: AnalyzeRequest,
    db: DbSession,
    service: ExecSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Исполнительный анализ бизнеса → план + приоритизированные действия (advisory)."""
    return _run(
        lambda: service.create_executive_plan(
            db, project_id, objective_id=payload.objective_id, user_id=user.id
        )
    )


@router.get("/projects/{project_id}/executive/plan", dependencies=[Depends(require_project_access)])
def get_plan(project_id: int, db: DbSession, service: ExecSvc, user: CurrentUser) -> dict[str, Any]:
    """Последний исполнительный план проекта + его действия."""
    return _run(lambda: service.get_plan(db, project_id))


@router.get(
    "/projects/{project_id}/executive/actions", dependencies=[Depends(require_project_access)]
)
def list_actions(
    project_id: int,
    db: DbSession,
    service: ExecSvc,
    user: CurrentUser,
    action_status: str | None = None,
) -> dict[str, Any]:
    """Список бизнес-действий проекта (по убыванию приоритета, опц. по статусу)."""
    return _run(lambda: {"actions": service.list_actions(db, project_id, status=action_status)})


@router.get(
    "/projects/{project_id}/executive/explanation", dependencies=[Depends(require_project_access)]
)
def get_explanation(
    project_id: int, db: DbSession, service: ExecSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение владельцу: почему AI выбрал именно эти приоритеты и действия."""
    return _run(lambda: service.explain_plan(db, project_id))


# --------------------------------------------------------------------------- #
# Action review & apply                                                       #
# --------------------------------------------------------------------------- #


@router.post("/actions/{action_id}/accept", dependencies=[Depends(require_action_access)])
def accept_action(
    action_id: int, db: DbSession, service: ExecSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить бизнес-действие (status=accepted)."""
    return _run(lambda: service.accept_action(db, action_id, user_id=user.id))


@router.post("/actions/{action_id}/reject", dependencies=[Depends(require_action_access)])
def reject_action(
    action_id: int, db: DbSession, service: ExecSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить бизнес-действие (status=rejected)."""
    return _run(lambda: service.reject_action(db, action_id, user_id=user.id))


@router.post("/actions/{action_id}/apply", dependencies=[Depends(require_action_access)])
def apply_action(
    action_id: int,
    payload: ConfirmRequest,
    db: DbSession,
    service: ExecSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить действие (accepted + confirmation APPLY_BUSINESS_ACTION). Live/CRM off."""
    return _run(
        lambda: service.apply_action(
            db, action_id, confirmation=payload.confirmation, user_id=user.id
        )
    )
