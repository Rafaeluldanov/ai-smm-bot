"""REST API AI Business Growth Agent — v0.6.9.

Клиентский слой «AI рост бизнеса»: состояние роста, запуск анализа + рекомендации,
review (accept/reject) и apply с подтверждением, объяснение. Всё под project-guard.
Advisory-слой: НЕ меняет бизнес/CRM/бюджет/live/публикации сам. Секретов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_business_growth_agent_service, get_current_user, get_db
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.business_growth_agent_service import (
    BusinessGrowthAgentService,
    BusinessGrowthError,
)

router = APIRouter(prefix="/projects", tags=["business-growth"])

DbSession = Annotated[Session, Depends(get_db)]
GrowthSvc = Annotated[BusinessGrowthAgentService, Depends(get_business_growth_agent_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except BusinessGrowthError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ApplyRequest(BaseModel):
    """Тело применения рекомендации (id + подтверждение)."""

    recommendation_id: int
    confirmation: str = ""


@router.get("/{project_id}/growth", dependencies=[Depends(require_project_access)])
def get_growth(
    project_id: int, db: DbSession, service: GrowthSvc, user: CurrentUser
) -> dict[str, Any]:
    """Текущее состояние роста бизнеса (профиль + счётчик открытых рекомендаций)."""
    return _run(lambda: service.get_growth(db, project_id))


@router.post("/{project_id}/growth/analyze", dependencies=[Depends(require_project_access)])
def analyze(
    project_id: int, db: DbSession, service: GrowthSvc, user: CurrentUser
) -> dict[str, Any]:
    """Проанализировать бизнес + сгенерировать рекомендации (advisory; live/CRM не трогает)."""
    return _run(lambda: service.analyze_and_recommend(db, project_id, user_id=user.id))


@router.get("/{project_id}/growth/recommendations", dependencies=[Depends(require_project_access)])
def list_recommendations(
    project_id: int,
    db: DbSession,
    service: GrowthSvc,
    user: CurrentUser,
    rec_status: str | None = None,
) -> dict[str, Any]:
    """Список рекомендаций роста (опционально по статусу)."""
    return _run(
        lambda: {"recommendations": service.list_recommendations(db, project_id, status=rec_status)}
    )


@router.post(
    "/{project_id}/growth/recommendations/{recommendation_id}/accept",
    dependencies=[Depends(require_project_access)],
)
def accept_recommendation(
    project_id: int,
    recommendation_id: int,
    db: DbSession,
    service: GrowthSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Одобрить рекомендацию роста (status=accepted)."""
    return _run(
        lambda: service.accept_recommendation(db, project_id, recommendation_id, user_id=user.id)
    )


@router.post(
    "/{project_id}/growth/recommendations/{recommendation_id}/reject",
    dependencies=[Depends(require_project_access)],
)
def reject_recommendation(
    project_id: int,
    recommendation_id: int,
    db: DbSession,
    service: GrowthSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Отклонить рекомендацию роста (status=rejected)."""
    return _run(
        lambda: service.reject_recommendation(db, project_id, recommendation_id, user_id=user.id)
    )


@router.post("/{project_id}/growth/apply", dependencies=[Depends(require_project_access)])
def apply_recommendation(
    project_id: int,
    payload: ApplyRequest,
    db: DbSession,
    service: GrowthSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить рекомендацию (нужен accepted + confirmation APPLY_GROWTH_ACTION). Live off."""
    return _run(
        lambda: service.apply_recommendation(
            db,
            project_id,
            payload.recommendation_id,
            confirmation=payload.confirmation,
            user_id=user.id,
        )
    )


@router.get("/{project_id}/growth/explanation", dependencies=[Depends(require_project_access)])
def get_explanation(
    project_id: int, db: DbSession, service: GrowthSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение для клиента: почему AI рекомендует это."""
    return _run(lambda: service.explain_growth(db, project_id))
