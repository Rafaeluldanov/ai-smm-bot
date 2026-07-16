"""REST API AI Optimization Governance Engine — v0.8.2.

Optimization Item → Governance Review → Approval → Ownership → Impact Tracking. Governance-слой:
управление портфелем улучшений. НЕ применяет улучшения, НЕ запускает эксперименты, НЕ меняет
бизнес/KPI/CRM/бюджет, НЕ выполняет задачи; approve/reject меняют лишь статусы governance.
Секретов в ответах нет. Все роуты — под tenant-guard (project / governance → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_optimization_governance_service, get_current_user, get_db
from app.api.security_guards import require_governance_access, require_project_access
from app.models.user import User
from app.services.ai_optimization_governance_service import (
    AIOptimizationGovernanceError,
    AIOptimizationGovernanceService,
)

router = APIRouter(tags=["optimization-governance"])

DbSession = Annotated[Session, Depends(get_db)]
GovernanceSvc = Annotated[
    AIOptimizationGovernanceService, Depends(get_ai_optimization_governance_service)
]
CurrentUser = Annotated[User, Depends(get_current_user)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIOptimizationGovernanceError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --------------------------------------------------------------------------- #
# Project-scoped                                                             #
# --------------------------------------------------------------------------- #


@router.post(
    "/projects/{project_id}/optimization-governance",
    dependencies=[Depends(require_project_access)],
)
def analyze_governance(
    project_id: int, db: DbSession, service: GovernanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Завести governance для оптимизаций проекта + метрики портфеля (advisory)."""
    return _run(lambda: service.run_governance_cycle(db, project_id, user_id=user.id))


@router.get(
    "/projects/{project_id}/optimization-governance",
    dependencies=[Depends(require_project_access)],
)
def list_governances(
    project_id: int,
    db: DbSession,
    service: GovernanceSvc,
    user: CurrentUser,
    governance_status: str | None = None,
    approval_status: str | None = None,
) -> dict[str, Any]:
    """Governance-записи проекта (опционально по статусам)."""
    return _run(
        lambda: {
            "governances": service.get_governances(
                db, project_id, status=governance_status, approval_status=approval_status
            )
        }
    )


@router.get(
    "/projects/{project_id}/optimization-portfolio",
    dependencies=[Depends(require_project_access)],
)
def portfolio_metrics(
    project_id: int, db: DbSession, service: GovernanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Метрики портфеля улучшений + выводы."""
    return _run(lambda: service.get_portfolio(db, project_id))


# --------------------------------------------------------------------------- #
# Governance-scoped                                                          #
# --------------------------------------------------------------------------- #


@router.get("/governance/{governance_id}", dependencies=[Depends(require_governance_access)])
def get_governance(
    governance_id: int, db: DbSession, service: GovernanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Governance + ревью + impacts + история назначений."""
    return _run(lambda: service.get_governance_detail(db, governance_id))


@router.post(
    "/governance/{governance_id}/review", dependencies=[Depends(require_governance_access)]
)
def submit_review(
    governance_id: int,
    db: DbSession,
    service: GovernanceSvc,
    user: CurrentUser,
    payload: Payload,
) -> dict[str, Any]:
    """Создать ревью governance (identified → review). НЕ утверждает."""
    return _run(
        lambda: service.submit_review(
            db,
            governance_id,
            reviewer_user_id=user.id,
            decision=str(payload.get("decision") or "comment"),
            comment=payload.get("comment"),
            user_id=user.id,
        )
    )


@router.post(
    "/governance/{governance_id}/approve", dependencies=[Depends(require_governance_access)]
)
def approve_governance(
    governance_id: int, db: DbSession, service: GovernanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Согласовать governance (approval_status=approved). НЕ запускает."""
    return _run(lambda: service.approve_optimization(db, governance_id, user_id=user.id))


@router.post(
    "/governance/{governance_id}/reject", dependencies=[Depends(require_governance_access)]
)
def reject_governance(
    governance_id: int, db: DbSession, service: GovernanceSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить governance (approval_status=rejected)."""
    return _run(lambda: service.reject_optimization(db, governance_id, user_id=user.id))


@router.post("/governance/{governance_id}/owner", dependencies=[Depends(require_governance_access)])
def assign_owner(
    governance_id: int,
    db: DbSession,
    service: GovernanceSvc,
    user: CurrentUser,
    payload: Payload,
) -> dict[str, Any]:
    """Назначить владельца governance (ТОЛЬКО участнику аккаунта, FAIL CLOSED)."""
    owner_user_id = payload.get("owner_user_id")
    if owner_user_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="owner_user_id обязателен"
        )
    return _run(
        lambda: service.assign_owner(
            db,
            governance_id,
            int(owner_user_id),
            role=str(payload.get("role") or "owner"),
            user_id=user.id,
        )
    )
