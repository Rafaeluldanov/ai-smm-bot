"""REST API AI Continuous Improvement Engine — v0.8.0.

Performance Result → Experience Memory → Learning Event → Pattern Analysis → Improvement Backlog →
Owner Review. Learning-слой: цикл обучения бизнеса. НЕ меняет бизнес/стратегию/KPI/CRM/бюджет, НЕ
выполняет задачи/улучшения, НЕ запускает рекламу/публикации; approve/reject меняют лишь статус.
Секретов в ответах нет. Все роуты — под tenant-guard (project / improvement → project).

ВАЖНО (route-коллизия): learning-роуты под `/projects/{id}/improvement/...` — namespace
`/projects/{id}/learning/*` уже занят слоем AI Learning (v0.5.x «Чему бот научился»).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_continuous_improvement_service, get_current_user, get_db
from app.api.security_guards import require_improvement_access, require_project_access
from app.models.user import User
from app.services.ai_continuous_improvement_service import (
    AIContinuousImprovementError,
    AIContinuousImprovementService,
)

router = APIRouter(tags=["improvement"])

DbSession = Annotated[Session, Depends(get_db)]
ImprovementSvc = Annotated[
    AIContinuousImprovementService, Depends(get_ai_continuous_improvement_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIContinuousImprovementError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --------------------------------------------------------------------------- #
# Project-scoped (learning namespaced /improvement to avoid /learning clash)  #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/improvement/analyze",
    dependencies=[Depends(require_project_access)],
)
def analyze_learning(
    project_id: int, db: DbSession, service: ImprovementSvc, user: CurrentUser
) -> dict[str, Any]:
    """Прогнать цикл обучения: опыт → события → паттерны → улучшения (advisory)."""
    return _run(lambda: service.run_learning_cycle(db, project_id, user_id=user.id))


@router.get(
    "/projects/{project_id}/improvement/history",
    dependencies=[Depends(require_project_access)],
)
def learning_history(
    project_id: int,
    db: DbSession,
    service: ImprovementSvc,
    user: CurrentUser,
    experience_type: str | None = None,
) -> dict[str, Any]:
    """История опыта + события обучения + сводка."""
    return _run(lambda: service.get_history(db, project_id, experience_type=experience_type))


@router.get("/projects/{project_id}/patterns", dependencies=[Depends(require_project_access)])
def list_patterns(
    project_id: int,
    db: DbSession,
    service: ImprovementSvc,
    user: CurrentUser,
    pattern_type: str | None = None,
) -> dict[str, Any]:
    """Паттерны проекта (что работает / что не работает / точки оптимизации)."""
    return _run(
        lambda: {"patterns": service.get_patterns(db, project_id, pattern_type=pattern_type)}
    )


@router.get("/projects/{project_id}/improvements", dependencies=[Depends(require_project_access)])
def list_improvements(
    project_id: int,
    db: DbSession,
    service: ImprovementSvc,
    user: CurrentUser,
    improvement_status: str | None = None,
) -> dict[str, Any]:
    """Backlog улучшений проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "improvements": service.get_improvements(db, project_id, status=improvement_status)
        }
    )


# --------------------------------------------------------------------------- #
# Improvement-scoped                                                          #
# --------------------------------------------------------------------------- #


@router.post(
    "/improvements/{improvement_id}/approve", dependencies=[Depends(require_improvement_access)]
)
def approve_improvement(
    improvement_id: int, db: DbSession, service: ImprovementSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить улучшение (status=accepted). НЕ применяет."""
    return _run(lambda: service.approve_improvement(db, improvement_id, user_id=user.id))


@router.post(
    "/improvements/{improvement_id}/reject", dependencies=[Depends(require_improvement_access)]
)
def reject_improvement(
    improvement_id: int, db: DbSession, service: ImprovementSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить улучшение (status=rejected). НЕ применяет."""
    return _run(lambda: service.reject_improvement(db, improvement_id, user_id=user.id))
