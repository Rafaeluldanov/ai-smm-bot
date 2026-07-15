"""REST API AI Campaign Manager — v0.6.7.

Клиентский слой «AI кампании»: создание кампании, планирование (стратегия+этапы+
рекомендации), review (accept/reject), approve и apply с подтверждением, предпросмотр
календаря. Всё под tenant-гардом. Кампания НЕ публикует, НЕ включает live и НЕ меняет
активный календарь. Секретов нет.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_campaign_manager_service, get_current_user, get_db
from app.api.security_guards import require_campaign_access, require_project_access
from app.models.user import User
from app.services.ai_campaign_manager_service import (
    AICampaignError,
    AICampaignManagerService,
)

router = APIRouter(tags=["ai-campaigns"])

DbSession = Annotated[Session, Depends(get_db)]
CampaignSvc = Annotated[AICampaignManagerService, Depends(get_ai_campaign_manager_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AICampaignError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class CreateCampaignRequest(BaseModel):
    """Тело создания кампании."""

    name: str
    goal: str
    description: str | None = None
    product_context: dict[str, Any] | None = None
    audience_context: dict[str, Any] | None = None
    business_context: dict[str, Any] | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class ApplyCampaignRequest(BaseModel):
    """Тело применения кампании (подтверждение)."""

    confirmation: str = ""


# ------------------------------------------------------------------ #
# Project-scoped routes                                              #
# ------------------------------------------------------------------ #


@router.post("/projects/{project_id}/campaigns", dependencies=[Depends(require_project_access)])
def create_campaign(
    project_id: int,
    payload: CreateCampaignRequest,
    db: DbSession,
    service: CampaignSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать кампанию (status=draft)."""
    return _run(
        lambda: service.create_campaign(
            db,
            project_id,
            name=payload.name,
            goal=payload.goal,
            description=payload.description,
            product_context=payload.product_context,
            audience_context=payload.audience_context,
            business_context=payload.business_context,
            start_date=payload.start_date,
            end_date=payload.end_date,
            user_id=user.id,
        )
    )


@router.get("/projects/{project_id}/campaigns", dependencies=[Depends(require_project_access)])
def list_campaigns(
    project_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Список кампаний проекта."""
    return _run(lambda: {"campaigns": service.list_campaigns(db, project_id)})


# ------------------------------------------------------------------ #
# Campaign-scoped routes                                            #
# ------------------------------------------------------------------ #


@router.get("/campaigns/{campaign_id}", dependencies=[Depends(require_campaign_access)])
def get_campaign(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Кампания + этапы."""
    return _run(lambda: service.get_campaign(db, campaign_id))


@router.post("/campaigns/{campaign_id}/generate", dependencies=[Depends(require_campaign_access)])
def generate_plan(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Спланировать кампанию: стратегия + этапы + рекомендации (не публикует, live off)."""
    return _run(lambda: service.plan_campaign(db, campaign_id, user_id=user.id))


@router.get("/campaigns/{campaign_id}/strategy", dependencies=[Depends(require_campaign_access)])
def get_strategy(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сохранённая стратегия кампании (read-only)."""
    return _run(lambda: service.get_strategy(db, campaign_id))


@router.get("/campaigns/{campaign_id}/explanation", dependencies=[Depends(require_campaign_access)])
def get_explanation(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение для клиента: почему AI построил такую кампанию."""
    return _run(lambda: service.explain_campaign(db, campaign_id))


@router.get(
    "/campaigns/{campaign_id}/recommendations", dependencies=[Depends(require_campaign_access)]
)
def list_recommendations(
    campaign_id: int,
    db: DbSession,
    service: CampaignSvc,
    user: CurrentUser,
    rec_status: str | None = None,
) -> dict[str, Any]:
    """Рекомендации кампании (опционально по статусу)."""
    return _run(
        lambda: {
            "recommendations": service.list_recommendations(db, campaign_id, status=rec_status)
        }
    )


@router.post(
    "/campaigns/{campaign_id}/recommendations/{recommendation_id}/accept",
    dependencies=[Depends(require_campaign_access)],
)
def accept_recommendation(
    campaign_id: int,
    recommendation_id: int,
    db: DbSession,
    service: CampaignSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Одобрить рекомендацию кампании (status=accepted)."""
    return _run(
        lambda: service.accept_recommendation(db, campaign_id, recommendation_id, user_id=user.id)
    )


@router.post(
    "/campaigns/{campaign_id}/recommendations/{recommendation_id}/reject",
    dependencies=[Depends(require_campaign_access)],
)
def reject_recommendation(
    campaign_id: int,
    recommendation_id: int,
    db: DbSession,
    service: CampaignSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Отклонить рекомендацию кампании (status=rejected)."""
    return _run(
        lambda: service.reject_recommendation(db, campaign_id, recommendation_id, user_id=user.id)
    )


@router.post("/campaigns/{campaign_id}/approve", dependencies=[Depends(require_campaign_access)])
def approve_campaign(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить кампанию (status=approved) — обязательный шаг перед apply."""
    return _run(lambda: service.approve_campaign(db, campaign_id, user_id=user.id))


@router.post("/campaigns/{campaign_id}/apply", dependencies=[Depends(require_campaign_access)])
def apply_campaign(
    campaign_id: int,
    payload: ApplyCampaignRequest,
    db: DbSession,
    service: CampaignSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Применить кампанию (нужен status=approved И confirmation=APPLY_CAMPAIGN). Live off, draft."""
    return _run(
        lambda: service.apply_campaign(
            db, campaign_id, confirmation=payload.confirmation, user_id=user.id
        )
    )


@router.get(
    "/campaigns/{campaign_id}/calendar-preview",
    dependencies=[Depends(require_campaign_access)],
)
def calendar_preview(
    campaign_id: int, db: DbSession, service: CampaignSvc, user: CurrentUser
) -> dict[str, Any]:
    """Предпросмотр будущего календаря кампании (week 1..4). Без записи."""
    return _run(lambda: service.campaign_calendar_preview(db, campaign_id))
