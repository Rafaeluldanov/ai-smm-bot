"""REST API AI Operations Control Center — v0.7.3.

Единая операционная панель: снапшот состояния + health, риски (resolve), рекомендации
(accept/reject), история. Аналитический/управленческий слой: НЕ выполняет действий, НЕ
меняет CRM/бюджет/продажи/live/публикации. Секретов в ответах нет. Все роуты — под
tenant-guard (project или risk/recommendation → project).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_ai_operations_control_service, get_current_user, get_db
from app.api.security_guards import (
    require_operations_recommendation_access,
    require_operations_risk_access,
    require_project_access,
)
from app.models.user import User
from app.services.ai_operations_control_service import (
    AIOperationsControlError,
    AIOperationsControlService,
)

router = APIRouter(tags=["operations"])

DbSession = Annotated[Session, Depends(get_db)]
OpsSvc = Annotated[AIOperationsControlService, Depends(get_ai_operations_control_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AIOperationsControlError as exc:
        message = str(exc)
        if "не найден" in message.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --------------------------------------------------------------------------- #
# Operations snapshot                                                         #
# --------------------------------------------------------------------------- #


@router.get("/projects/{project_id}/operations", dependencies=[Depends(require_project_access)])
def get_operations(
    project_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Последний операционный снапшот + открытые риски + рекомендации."""
    return _run(lambda: service.get_operations(db, project_id))


@router.post(
    "/projects/{project_id}/operations/analyze", dependencies=[Depends(require_project_access)]
)
def analyze_operations(
    project_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Собрать снапшот: сигналы → health → риски → рекомендации (advisory; действий нет)."""
    return _run(lambda: service.build_operations_snapshot(db, project_id, user_id=user.id))


@router.get(
    "/projects/{project_id}/operations/history", dependencies=[Depends(require_project_access)]
)
def operations_history(
    project_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """История операционных снапшотов (тренд health)."""
    return _run(lambda: {"history": service.get_history(db, project_id)})


@router.get(
    "/projects/{project_id}/operations/explanation",
    dependencies=[Depends(require_project_access)],
)
def operations_explanation(
    project_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение владельцу: почему здоровье бизнеса именно такое."""
    return _run(lambda: service.explain_operations_state(db, project_id))


# --------------------------------------------------------------------------- #
# Risks                                                                       #
# --------------------------------------------------------------------------- #


@router.get(
    "/projects/{project_id}/operations/risks", dependencies=[Depends(require_project_access)]
)
def list_risks(
    project_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Открытые операционные риски проекта."""
    return _run(lambda: {"risks": service.list_active_risks(db, project_id)})


@router.post("/risks/{risk_id}/resolve", dependencies=[Depends(require_operations_risk_access)])
def resolve_risk(risk_id: int, db: DbSession, service: OpsSvc, user: CurrentUser) -> dict[str, Any]:
    """Снять риск (status=resolved). НЕ выполняет действий."""
    return _run(lambda: service.resolve_risk(db, risk_id, user_id=user.id))


# --------------------------------------------------------------------------- #
# Recommendations                                                             #
# --------------------------------------------------------------------------- #


@router.get(
    "/projects/{project_id}/operations/recommendations",
    dependencies=[Depends(require_project_access)],
)
def list_recommendations(
    project_id: int,
    db: DbSession,
    service: OpsSvc,
    user: CurrentUser,
    rec_status: str | None = None,
) -> dict[str, Any]:
    """Операционные рекомендации проекта (опционально по статусу)."""
    return _run(
        lambda: {"recommendations": service.list_recommendations(db, project_id, status=rec_status)}
    )


@router.post(
    "/recommendations/{recommendation_id}/accept",
    dependencies=[Depends(require_operations_recommendation_access)],
)
def accept_recommendation(
    recommendation_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Одобрить рекомендацию (status=accepted). НЕ выполняет действие."""
    return _run(lambda: service.accept_recommendation(db, recommendation_id, user_id=user.id))


@router.post(
    "/recommendations/{recommendation_id}/reject",
    dependencies=[Depends(require_operations_recommendation_access)],
)
def reject_recommendation(
    recommendation_id: int, db: DbSession, service: OpsSvc, user: CurrentUser
) -> dict[str, Any]:
    """Отклонить рекомендацию (status=rejected)."""
    return _run(lambda: service.reject_recommendation(db, recommendation_id, user_id=user.id))
