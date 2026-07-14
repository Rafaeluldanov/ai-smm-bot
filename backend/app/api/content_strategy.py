"""REST API автономного контент-стратега — v0.6.6.

Клиентский слой «AI стратегия контента»: снапшот стратегии, генерация рекомендаций,
review (accept/reject) и apply с подтверждением. Всё под project-guard. Стратегия НЕ
включает live, НЕ публикует и НЕ меняет активный календарь сама. Секретов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_content_strategist_service, get_current_user, get_db
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.content_strategist_service import (
    ContentStrategistError,
    ContentStrategistService,
)

router = APIRouter(prefix="/projects", tags=["content-strategy"])

DbSession = Annotated[Session, Depends(get_db)]
StrategistSvc = Annotated[ContentStrategistService, Depends(get_content_strategist_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except ContentStrategistError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ApplyRequest(BaseModel):
    """Тело применения рекомендации (id + подтверждение)."""

    recommendation_id: int
    confirmation: str = ""


@router.get("/{project_id}/strategy", dependencies=[Depends(require_project_access)])
def get_strategy(
    project_id: int, db: DbSession, service: StrategistSvc, user: CurrentUser
) -> dict[str, Any]:
    """Текущая стратегия проекта (профиль + счётчик открытых рекомендаций)."""
    return _run(lambda: service.get_strategy(db, project_id))


@router.post("/{project_id}/strategy/analyze", dependencies=[Depends(require_project_access)])
def analyze_strategy(
    project_id: int, db: DbSession, service: StrategistSvc, user: CurrentUser
) -> dict[str, Any]:
    """Собрать снапшот + месячный план + сгенерировать рекомендации (не публикует, live off)."""

    def _analyze() -> dict[str, Any]:
        # Снапшот строится ОДИН раз и переиспользуется (без тройного пересчёта/коммитов).
        snapshot = service.build_strategy_snapshot(db, project_id)
        return {
            "snapshot": snapshot,
            "next_month": service.recommend_next_month(db, project_id, snapshot=snapshot),
            "generated": service.generate_recommendations(
                db, project_id, user_id=user.id, snapshot=snapshot
            ),
        }

    return _run(_analyze)


@router.get(
    "/{project_id}/strategy/recommendations", dependencies=[Depends(require_project_access)]
)
def list_recommendations(
    project_id: int,
    db: DbSession,
    service: StrategistSvc,
    user: CurrentUser,
    rec_status: str | None = None,
) -> dict[str, Any]:
    """Список рекомендаций проекта (опционально по статусу)."""
    return _run(
        lambda: {"recommendations": service.list_recommendations(db, project_id, status=rec_status)}
    )


@router.post(
    "/{project_id}/strategy/recommendations/{recommendation_id}/accept",
    dependencies=[Depends(require_project_access)],
)
def accept_recommendation(
    project_id: int,
    recommendation_id: int,
    db: DbSession,
    service: StrategistSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Одобрить рекомендацию (status=accepted)."""
    return _run(
        lambda: service.accept_recommendation(db, project_id, recommendation_id, user_id=user.id)
    )


@router.post(
    "/{project_id}/strategy/recommendations/{recommendation_id}/reject",
    dependencies=[Depends(require_project_access)],
)
def reject_recommendation(
    project_id: int,
    recommendation_id: int,
    db: DbSession,
    service: StrategistSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Отклонить рекомендацию (status=rejected)."""
    return _run(
        lambda: service.reject_recommendation(db, project_id, recommendation_id, user_id=user.id)
    )


@router.post("/{project_id}/strategy/apply", dependencies=[Depends(require_project_access)])
def apply_recommendation(
    project_id: int,
    payload: ApplyRequest,
    db: DbSession,
    service: StrategistSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить рекомендацию (нужен status=accepted И confirmation=APPLY_STRATEGY). Live off."""
    return _run(
        lambda: service.apply_recommendation(
            db,
            project_id,
            payload.recommendation_id,
            confirmation=payload.confirmation,
            user_id=user.id,
        )
    )


@router.get("/{project_id}/strategy/explanation", dependencies=[Depends(require_project_access)])
def get_explanation(
    project_id: int, db: DbSession, service: StrategistSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение для клиента: почему бот выбрал эти темы/форматы."""
    return _run(lambda: service.explain_strategy(db, project_id))
