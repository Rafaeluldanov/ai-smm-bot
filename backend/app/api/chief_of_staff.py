"""REST API AI Chief of Staff / Executive Assistant Layer — v0.7.1.

Персональный AI-ассистент владельца: executive briefing (daily/weekly), задачи владельца
(suggest → accept/reject → complete) и память решений. Advisory + assistant слой: НЕ
выполняет задачи, НЕ меняет бизнес/CRM/бюджет/продажи/live/публикации. Секретов в ответах
нет. Все роуты — под tenant-guard (project или task/decision → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_ai_chief_of_staff_service, get_current_user, get_db
from app.api.security_guards import (
    require_decision_access,
    require_project_access,
    require_task_access,
)
from app.models.user import User
from app.services.ai_chief_of_staff_service import AIChiefOfStaffError, AIChiefOfStaffService

router = APIRouter(tags=["chief-of-staff"])

DbSession = Annotated[Session, Depends(get_db)]
ChiefSvc = Annotated[AIChiefOfStaffService, Depends(get_ai_chief_of_staff_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIChiefOfStaffError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class DecisionRequest(BaseModel):
    """Запоминание решения владельца."""

    decision_type: str
    key: str = Field(max_length=80)
    value: dict[str, Any] = {}
    reason: str | None = None


# --------------------------------------------------------------------------- #
# Briefings                                                                   #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/briefing", dependencies=[Depends(require_project_access)])
def get_briefing(
    project_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Последний брифинг проекта (+ его задачи)."""
    return _run(lambda: service.get_latest_briefing(db, project_id))


@router.post(
    "/projects/{project_id}/briefing/generate", dependencies=[Depends(require_project_access)]
)
def generate_briefing(
    project_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сформировать ежедневный executive briefing + задачи (advisory; ничего не выполняет)."""
    return _run(lambda: service.generate_daily_briefing(db, project_id, user_id=user.id))


@router.post(
    "/projects/{project_id}/briefing/weekly", dependencies=[Depends(require_project_access)]
)
def generate_weekly(
    project_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сформировать Weekly Business Review (7 дней против предыдущих 7 дней)."""
    return _run(lambda: service.generate_weekly_review(db, project_id, user_id=user.id))


# --------------------------------------------------------------------------- #
# Owner tasks                                                                 #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/tasks", dependencies=[Depends(require_project_access)])
def list_tasks(
    project_id: int,
    db: DbSession,
    service: ChiefSvc,
    user: CurrentUser,
    task_status: str | None = None,
) -> dict[str, Any]:
    """Список задач владельца (по убыванию приоритета, опц. по статусу)."""
    return _run(lambda: {"tasks": service.list_tasks(db, project_id, status=task_status)})


@router.post("/tasks/{task_id}/accept", dependencies=[Depends(require_task_access)])
def accept_task(
    task_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить задачу (status=accepted). НЕ выполняет действие."""
    return _run(lambda: service.accept_task(db, task_id, user_id=user.id))


@router.post("/tasks/{task_id}/reject", dependencies=[Depends(require_task_access)])
def reject_task(
    task_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить задачу (status=rejected)."""
    return _run(lambda: service.reject_task(db, task_id, user_id=user.id))


@router.post("/tasks/{task_id}/complete", dependencies=[Depends(require_task_access)])
def complete_task(
    task_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Зафиксировать выполнение задачи (status=completed). Внешних действий нет."""
    return _run(lambda: service.complete_task(db, task_id, user_id=user.id))


# --------------------------------------------------------------------------- #
# Decision memory                                                             #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/decisions", dependencies=[Depends(require_project_access)])
def save_decision(
    project_id: int,
    payload: DecisionRequest,
    db: DbSession,
    service: ChiefSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Запомнить решение владельца (предпочтение/стратегия/ограничение/одобрение)."""
    return _run(
        lambda: service.save_decision_memory(
            db,
            project_id,
            decision_type=payload.decision_type,
            key=payload.key,
            value=payload.value,
            reason=payload.reason,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/decisions", dependencies=[Depends(require_project_access)])
def list_decisions(
    project_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Список активных запомненных решений владельца."""
    return _run(lambda: {"decisions": service.get_decisions(db, project_id)})


@router.delete("/decisions/{decision_id}", dependencies=[Depends(require_decision_access)])
def disable_decision(
    decision_id: int, db: DbSession, service: ChiefSvc, user: CurrentUser
) -> dict[str, Any]:
    """Деактивировать запомненное решение (active=False). Запись не удаляется."""
    return _run(lambda: service.disable_decision(db, decision_id, user_id=user.id))
