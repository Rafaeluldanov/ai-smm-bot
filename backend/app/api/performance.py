"""REST API AI Performance Intelligence Engine — v0.7.9.

Execution Plan → Performance Snapshot → Actual vs Target → Deviation Analysis → Recommendations.
Аналитический слой: измеряет эффективность исполнения. НЕ меняет планы/KPI/CRM/бюджет, НЕ выполняет
задачи/рекомендации, НЕ запускает рекламу/публикации. Секретов в ответах нет. Все роуты — под
tenant-guard (project / snapshot → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_performance_intelligence_service, get_current_user, get_db
from app.api.security_guards import require_performance_snapshot_access, require_project_access
from app.models.user import User
from app.services.ai_performance_intelligence_service import (
    AIPerformanceIntelligenceError,
    AIPerformanceIntelligenceService,
)

router = APIRouter(tags=["performance"])

DbSession = Annotated[Session, Depends(get_db)]
PerformanceSvc = Annotated[
    AIPerformanceIntelligenceService, Depends(get_ai_performance_intelligence_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIPerformanceIntelligenceError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --------------------------------------------------------------------------- #
# Project-scoped                                                              #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/performance/analyze",
    dependencies=[Depends(require_project_access)],
)
def analyze_performance(
    project_id: int, db: DbSession, service: PerformanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Собрать снимок эффективности: факт vs план → score → отклонения → рекомендации (advisory)."""
    return _run(lambda: service.create_snapshot(db, project_id, user_id=user.id))


@router.get("/projects/{project_id}/performance", dependencies=[Depends(require_project_access)])
def list_performance(
    project_id: int,
    db: DbSession,
    service: PerformanceSvc,
    user: CurrentUser,
    snapshot_status: str | None = None,
) -> dict[str, Any]:
    """Список снимков эффективности проекта + сводка."""
    return _run(lambda: service.list_snapshots(db, project_id, status=snapshot_status))


# --------------------------------------------------------------------------- #
# Snapshot-scoped                                                            #
# --------------------------------------------------------------------------- #


@router.get(
    "/performance/{snapshot_id}", dependencies=[Depends(require_performance_snapshot_access)]
)
def get_snapshot(
    snapshot_id: int, db: DbSession, service: PerformanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Снимок + метрики + отклонения + рекомендации + объяснение."""
    return _run(
        lambda: {
            **service.get_snapshot(db, snapshot_id),
            "explanation": service.explain_performance(db, snapshot_id),
        }
    )


@router.get(
    "/performance/{snapshot_id}/metrics",
    dependencies=[Depends(require_performance_snapshot_access)],
)
def get_metrics(
    snapshot_id: int, db: DbSession, service: PerformanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Метрики снимка (план vs факт)."""
    return _run(lambda: {"metrics": service.get_metrics(db, snapshot_id)})


@router.get(
    "/performance/{snapshot_id}/deviations",
    dependencies=[Depends(require_performance_snapshot_access)],
)
def get_deviations(
    snapshot_id: int, db: DbSession, service: PerformanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонения снимка."""
    return _run(lambda: {"deviations": service.get_deviations(db, snapshot_id)})


@router.get(
    "/performance/{snapshot_id}/recommendations",
    dependencies=[Depends(require_performance_snapshot_access)],
)
def get_recommendations(
    snapshot_id: int, db: DbSession, service: PerformanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Рекомендации снимка + объяснение."""
    return _run(
        lambda: {
            "recommendations": service.get_recommendations(db, snapshot_id),
            "explanation": service.explain_performance(db, snapshot_id),
        }
    )
