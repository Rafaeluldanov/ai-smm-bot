"""REST API клиентского онбординга — «запуск автопилота за 5 минут» (v0.6.4).

5 шагов (бизнес → материалы → площадки → цель → запуск). Все роуты требуют auth; сессия строго
привязана к пользователю (tenant isolation в сервисе). Секретов/токенов в ответах нет; онбординг
НЕ включает live-публикацию (после завершения — READY, но LIVE=OFF).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_client_onboarding_service, get_current_user, get_db
from app.models.user import User
from app.services.client_onboarding_service import (
    ClientOnboardingError,
    ClientOnboardingService,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

DbSession = Annotated[Session, Depends(get_db)]
OnboardingSvc = Annotated[ClientOnboardingService, Depends(get_client_onboarding_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except ClientOnboardingError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


@router.post("/start")
def start(
    db: DbSession, service: OnboardingSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Начать онбординг (или вернуть активную сессию)."""
    return _run(
        lambda: service.start_onboarding(
            db, user.id, company_name=str(payload.get("company_name") or "") or None
        )
    )


@router.get("/{session_id}")
def get_session(
    session_id: int, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Текущее состояние сессии онбординга."""
    return _run(lambda: service.get_session(db, session_id, user_id=user.id))


@router.post("/{session_id}/business")
def business(
    session_id: int, payload: Payload, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Шаг 1: «Ваш бизнес»."""
    return _run(lambda: service.complete_business_step(db, session_id, payload, user_id=user.id))


@router.post("/{session_id}/media")
def media(
    session_id: int, payload: Payload, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Шаг 2: «Ваши материалы» (Яндекс Диск — без запуска синхронизации)."""
    return _run(lambda: service.complete_media_step(db, session_id, payload, user_id=user.id))


@router.post("/{session_id}/platforms")
def platforms(
    session_id: int, payload: Payload, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Шаг 3: «Где публиковать»."""
    return _run(lambda: service.complete_platform_step(db, session_id, payload, user_id=user.id))


@router.post("/{session_id}/goal")
def goal(
    session_id: int, payload: Payload, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Шаг 4: «Что должен делать автопилот» (цель + частота → календарь)."""
    return _run(lambda: service.complete_goal_step(db, session_id, payload, user_id=user.id))


@router.post("/{session_id}/finish")
def finish(
    session_id: int, db: DbSession, service: OnboardingSvc, user: CurrentUser
) -> dict[str, Any]:
    """Шаг 5: «Запустите автопилот» — готовность + первый preview. LIVE остаётся OFF."""
    return _run(lambda: service.finish_onboarding(db, session_id, user_id=user.id))
