"""REST API AI Business Pilot Release — v1.0.0 (первый бизнес-пилот).

Онбординг реальной компании, бизнес-цели, KPI, AI Business Intelligence Report, CEO Daily Brief и
feedback loop. Всё advisory: AI ТОЛЬКО анализирует/прогнозирует/рекомендует. НЕ выполняет
рекомендаций, НЕ меняет бизнес/CRM/финансы, НЕ запускает рекламу, НЕ публикует, НЕ шлёт сообщений,
НЕ создаёт платежей. Секретов нет. Все роуты требуют авторизации; доступ к pilot-ресурсам —
только участнику аккаунта; при pilot_mode=false pilot-действия запрещены (403).

ВАЖНО (route-namespace): онбординг под `/pilot/onboarding`; операции воркспейса под
`/pilot/{workspace_id}/*` (goals/kpis/intelligence/daily-brief/feedback) — не пересекается с
`/pilot/workspaces/*` из pilot.py (разная глубина/сегменты).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_ceo_daily_brief_service,
    get_ai_pilot_feedback_service,
    get_ai_pilot_intelligence_report_service,
    get_ai_pilot_onboarding_service,
    get_current_user,
    get_db,
)
from app.models.user import User
from app.repositories import pilot_repository as repo
from app.services import saas_security_service as security
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
)
from app.services.ai_ceo_daily_brief_service import AICEODailyBriefService
from app.services.ai_pilot_feedback_service import AIPilotFeedbackService
from app.services.ai_pilot_intelligence_report_service import AIPilotIntelligenceReportService
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

router = APIRouter(tags=["pilot-release"])

DbSession = Annotated[Session, Depends(get_db)]
OnboardingSvc = Annotated[AIPilotOnboardingService, Depends(get_ai_pilot_onboarding_service)]
IntelligenceSvc = Annotated[
    AIPilotIntelligenceReportService, Depends(get_ai_pilot_intelligence_report_service)
]
DailyBriefSvc = Annotated[AICEODailyBriefService, Depends(get_ai_ceo_daily_brief_service)]
FeedbackSvc = Annotated[AIPilotFeedbackService, Depends(get_ai_pilot_feedback_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Payload = Annotated[dict[str, Any], Body(default_factory=dict)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except PilotModeDisabledError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AIBusinessPilotError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


def _require_account_access(db: Session, user: User, account_id: int | None) -> None:
    """Доступ пользователя к аккаунту pilot-ресурса (None — dev/legacy, разрешено)."""
    if account_id is None:
        return
    if not security.user_can_access_account(db, user, account_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")


def _require_workspace(db: Session, user: User, workspace_id: int) -> Any:
    """Воркспейс существует и принадлежит доступному пользователю аккаунту (иначе 404)."""
    workspace = repo.get_workspace(db, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    _require_account_access(db, user, workspace.account_id)
    return workspace


def _as_int(value: Any, field: str) -> int:
    """Привести к int; невалидный ввод → 400 (а не необработанный 500)."""
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Поле «{field}» должно быть числом"
        ) from exc


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #


@router.post("/pilot/onboarding")
def onboard_company(
    db: DbSession, service: OnboardingSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Онбординг реальной компании: workspace → profile → goal(s) → KPI(s) (участнику аккаунта)."""
    account_id = payload.get("account_id")
    if account_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="account_id обязателен")
    account_id = _as_int(account_id, "account_id")
    _require_account_access(db, user, account_id)
    return _run(
        lambda: service.create_company_pilot(
            db,
            account_id,
            company_name=str(payload.get("company_name") or "Pilot Company"),
            industry=str(payload.get("industry") or ""),
            profile=payload.get("profile"),
            goals=payload.get("goals"),
            kpis=payload.get("kpis"),
            user_id=user.id,
        )
    )


@router.post("/pilot/{workspace_id}/goals")
def create_goal(
    workspace_id: int, db: DbSession, service: OnboardingSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Добавить бизнес-цель пилота."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.create_goal(db, workspace_id, payload, user_id=user.id))


@router.post("/pilot/{workspace_id}/kpis")
def create_kpi(
    workspace_id: int, db: DbSession, service: OnboardingSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Добавить KPI пилота."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.create_kpi(db, workspace_id, payload, user_id=user.id))


@router.get("/pilot/{workspace_id}/intelligence")
def intelligence_report(
    workspace_id: int, db: DbSession, service: IntelligenceSvc, user: CurrentUser
) -> dict[str, Any]:
    """AI Business Intelligence Report (SWOT + AI-рекомендации; read-only, advisory)."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.generate_intelligence_report(db, workspace_id, user_id=user.id))


@router.get("/pilot/{workspace_id}/daily-brief")
def daily_brief(
    workspace_id: int, db: DbSession, service: DailyBriefSvc, user: CurrentUser
) -> dict[str, Any]:
    """CEO Daily Brief (health/событие/риски/возможности/действия/прогноз; read-only, advisory)."""
    _require_workspace(db, user, workspace_id)
    return _run(lambda: service.generate_daily_brief(db, workspace_id, user_id=user.id))


@router.post("/pilot/{workspace_id}/feedback")
def submit_feedback(
    workspace_id: int, db: DbSession, service: FeedbackSvc, user: CurrentUser, payload: Payload
) -> dict[str, Any]:
    """Сохранить решение владельца по AI-рекомендации (accepted/rejected/modified).

    Feedback ТОЛЬКО фиксируется — НЕ выполняет рекомендацию и бизнес не меняет.
    """
    _require_workspace(db, user, workspace_id)
    return _run(
        lambda: service.submit_feedback(
            db,
            workspace_id,
            decision=str(payload.get("decision") or ""),
            recommendation_id=(
                _as_int(payload["recommendation_id"], "recommendation_id")
                if payload.get("recommendation_id") is not None
                else None
            ),
            comment=payload.get("comment"),
            result=payload.get("result"),
            user_id=user.id,
        )
    )
