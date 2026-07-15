"""REST API AI Business Forecasting Engine — v0.7.6.

Business State → Forecast Model → KPI Projection → Risk Adjustment → Business Outlook → Owner
Review. Аналитический прогнозный слой: прогноз развития бизнеса на 3/6/12 месяцев. НЕ гарантирует
прибыль, НЕ обещает финансовый результат, НЕ меняет бизнес/CRM/бюджет, НЕ выполняет стратегии,
НЕ ходит во внешние API. Секретов в ответах нет. Все роуты — под tenant-guard (project /
forecast → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_ai_business_forecasting_service, get_current_user, get_db
from app.api.security_guards import require_forecast_access, require_project_access
from app.models.user import User
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    AIBusinessForecastingService,
)

router = APIRouter(tags=["business-forecasting"])

DbSession = Annotated[Session, Depends(get_db)]
ForecastSvc = Annotated[AIBusinessForecastingService, Depends(get_ai_business_forecasting_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIBusinessForecastingError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ForecastRequest(BaseModel):
    """Создание прогноза развития бизнеса."""

    horizon: str = "12_months"
    title: str | None = None


# --------------------------------------------------------------------------- #
# Forecasts                                                                   #
# --------------------------------------------------------------------------- #


@router.post("/projects/{project_id}/forecasts", dependencies=[Depends(require_project_access)])
def create_forecast(
    project_id: int,
    payload: ForecastRequest,
    db: DbSession,
    service: ForecastSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать прогноз из текущего состояния бизнеса. НЕ запускает проекцию (advisory)."""
    return _run(
        lambda: service.create_forecast(
            db, project_id, horizon=payload.horizon, title=payload.title, user_id=user.id
        )
    )


@router.get("/projects/{project_id}/forecasts", dependencies=[Depends(require_project_access)])
def list_forecasts(
    project_id: int,
    db: DbSession,
    service: ForecastSvc,
    user: CurrentUser,
    forecast_status: str | None = None,
) -> dict[str, Any]:
    """Список прогнозов проекта (опционально по статусу)."""
    return _run(
        lambda: {
            "forecasts": service.list_forecasts(db, project_id, status=forecast_status),
            "summary": service.get_summary(db, project_id),
        }
    )


@router.get("/forecasts/{forecast_id}", dependencies=[Depends(require_forecast_access)])
def get_forecast(
    forecast_id: int, db: DbSession, service: ForecastSvc, user: CurrentUser
) -> dict[str, Any]:
    """Прогноз + метрики + roadmap."""
    return _run(lambda: service.get_forecast(db, forecast_id))


@router.post("/forecasts/{forecast_id}/generate", dependencies=[Depends(require_forecast_access)])
def generate_forecast(
    forecast_id: int, db: DbSession, service: ForecastSvc, user: CurrentUser
) -> dict[str, Any]:
    """Запустить генерацию: baseline → KPI (3/6/12) → риск → outlook → roadmap (advisory)."""
    return _run(lambda: service.generate_business_outlook(db, forecast_id, user_id=user.id))


@router.get("/forecasts/{forecast_id}/metrics", dependencies=[Depends(require_forecast_access)])
def get_metrics(
    forecast_id: int, db: DbSession, service: ForecastSvc, user: CurrentUser
) -> dict[str, Any]:
    """KPI-проекции прогноза + объяснение."""
    return _run(
        lambda: {
            "metrics": service.get_metrics(db, forecast_id),
            "explanation": service.explain_forecast(db, forecast_id),
        }
    )


@router.get("/forecasts/{forecast_id}/roadmap", dependencies=[Depends(require_forecast_access)])
def get_roadmap(
    forecast_id: int, db: DbSession, service: ForecastSvc, user: CurrentUser
) -> dict[str, Any]:
    """Квартальный roadmap прогноза."""
    return _run(lambda: {"roadmap": service.get_roadmap(db, forecast_id)})


@router.get(
    "/projects/{project_id}/business-outlook", dependencies=[Depends(require_project_access)]
)
def business_outlook(
    project_id: int, db: DbSession, service: ForecastSvc, user: CurrentUser
) -> dict[str, Any]:
    """Бизнес-outlook проекта: последний прогноз + baseline + метрики + roadmap."""
    return _run(lambda: service.get_business_outlook(db, project_id))
