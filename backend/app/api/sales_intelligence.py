"""REST API AI Sales & Lead Intelligence — v0.6.8.

Клиентский слой «AI продажи из контента»: профиль/рекомендации, запуск анализа
(атрибуция контент→лид→выручка), приём событий лидов, отчёт по выручке, объяснение,
сброс. Всё под project-guard. Аналитический слой: НЕ шлёт клиентам, НЕ меняет CRM,
НЕ включает live, НЕ продаёт. Секретов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_sales_intelligence_service, get_current_user, get_db
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.ai_sales_intelligence_service import (
    AISalesIntelligenceError,
    AISalesIntelligenceService,
)

router = APIRouter(prefix="/projects", tags=["sales-intelligence"])

DbSession = Annotated[Session, Depends(get_db)]
SalesSvc = Annotated[AISalesIntelligenceService, Depends(get_ai_sales_intelligence_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AISalesIntelligenceError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class LeadEventRequest(BaseModel):
    """Тело регистрации события лида/выручки."""

    event_type: str  # lead_created | deal_created | deal_won | revenue_added
    source_type: str = "manual"
    status: str = "new"
    post_id: int | None = None
    campaign_id: int | None = None
    platform_key: str | None = None
    value: float = 0.0
    metadata: dict[str, Any] | None = None


@router.get("/{project_id}/sales-intelligence", dependencies=[Depends(require_project_access)])
def get_sales_intelligence(
    project_id: int, db: DbSession, service: SalesSvc, user: CurrentUser
) -> dict[str, Any]:
    """Профиль продаж + сводка выручки + рекомендации."""
    return _run(lambda: service.get_intelligence(db, project_id))


@router.post(
    "/{project_id}/sales-intelligence/analyze", dependencies=[Depends(require_project_access)]
)
def analyze(project_id: int, db: DbSession, service: SalesSvc, user: CurrentUser) -> dict[str, Any]:
    """Пересчитать профиль продаж + атрибуцию (не публикует, live off, CRM не трогает)."""
    return _run(lambda: service.build_sales_profile(db, project_id, user_id=user.id))


@router.post(
    "/{project_id}/sales-intelligence/leads", dependencies=[Depends(require_project_access)]
)
def create_lead(
    project_id: int,
    payload: LeadEventRequest,
    db: DbSession,
    service: SalesSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Зарегистрировать событие лида/выручки (сигнал для атрибуции)."""
    return _run(
        lambda: service.record_lead_event(
            db,
            project_id,
            event_type=payload.event_type,
            source_type=payload.source_type,
            status=payload.status,
            post_id=payload.post_id,
            campaign_id=payload.campaign_id,
            platform_key=payload.platform_key,
            value=payload.value,
            metadata=payload.metadata,
            user_id=user.id,
        )
    )


@router.get(
    "/{project_id}/sales-intelligence/revenue", dependencies=[Depends(require_project_access)]
)
def get_revenue(
    project_id: int, db: DbSession, service: SalesSvc, user: CurrentUser
) -> dict[str, Any]:
    """Что приносит деньги: топ-контент/кампании/CTA/площадка + сводка (read-only)."""
    return _run(lambda: service.get_revenue(db, project_id))


@router.get(
    "/{project_id}/sales-intelligence/explanation", dependencies=[Depends(require_project_access)]
)
def get_explanation(
    project_id: int, db: DbSession, service: SalesSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение для клиента: какие публикации принесли больше всего заявок/денег."""
    return _run(lambda: service.explain_revenue(db, project_id))


@router.post(
    "/{project_id}/sales-intelligence/reset", dependencies=[Depends(require_project_access)]
)
def reset(project_id: int, db: DbSession, service: SalesSvc, user: CurrentUser) -> dict[str, Any]:
    """Сбросить агрегаты профиля + атрибуцию (историю событий лидов НЕ удаляем)."""
    return _run(lambda: service.reset(db, project_id, user_id=user.id))
