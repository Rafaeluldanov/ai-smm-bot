"""REST API готовности к реальной автопубликации (live autopost readiness) — v0.5.9.

Клиентский слой «Готовность к автопубликации»: дашборд, проверки проекта/площадок, включение/
выключение live (project/platform/full-auto) с явным подтверждением, эффективный live-гейт. Всё под
project-гардом. Секретов/сырых токенов в ответах нет; API НЕ включает и НЕ обходит глобальные
live-флаги; реальных публикаций и внешних probe-вызовов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_live_readiness_service
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.live_readiness_service import LiveReadinessError, LiveReadinessService

router = APIRouter(
    prefix="/live-readiness",
    tags=["live-readiness"],
    dependencies=[Depends(require_project_access)],
)

DbSession = Annotated[Session, Depends(get_db)]
ReadinessSvc = Annotated[LiveReadinessService, Depends(get_live_readiness_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except LiveReadinessError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class ConfirmationRequest(BaseModel):
    """Подтверждение включения live (текст-подтверждение)."""

    confirmation: str = ""


@router.get("/projects/{project_id}")
def dashboard(
    project_id: int, db: DbSession, service: ReadinessSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд готовности к реальной автопубликации."""
    return _run(lambda: service.build_project_live_dashboard(db, project_id))


@router.post("/projects/{project_id}/check")
def check_project(
    project_id: int, db: DbSession, service: ReadinessSvc, user: CurrentUser
) -> dict[str, Any]:
    """Запустить проверку готовности проекта (пишет профиль)."""
    return _run(
        lambda: service.run_project_readiness_check(
            db, project_id, current_user_id=user.id, dry_run=False
        )
    )


@router.post("/projects/{project_id}/platforms/{platform_key}/check")
def check_platform(
    project_id: int,
    platform_key: str,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Запустить проверку готовности площадки (пишет профиль)."""
    return _run(
        lambda: service.run_platform_readiness_check(
            db, project_id, platform_key, current_user_id=user.id, dry_run=False
        )
    )


@router.post("/projects/{project_id}/enable")
def enable_project(
    project_id: int,
    payload: ConfirmationRequest,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Включить live для проекта (подтверждение обязательно; глобальные флаги не трогает)."""
    return _run(
        lambda: service.enable_project_live(
            db, project_id, payload.confirmation, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/disable")
def disable_project(
    project_id: int, db: DbSession, service: ReadinessSvc, user: CurrentUser
) -> dict[str, Any]:
    """Выключить live для проекта (и full-auto)."""
    return _run(lambda: service.disable_project_live(db, project_id, current_user_id=user.id))


@router.post("/projects/{project_id}/platforms/{platform_key}/enable")
def enable_platform(
    project_id: int,
    platform_key: str,
    payload: ConfirmationRequest,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Включить live для площадки (подтверждение обязательно; глобальные флаги не трогает)."""
    return _run(
        lambda: service.enable_platform_live(
            db, project_id, platform_key, payload.confirmation, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/platforms/{platform_key}/disable")
def disable_platform(
    project_id: int,
    platform_key: str,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Выключить live для площадки."""
    return _run(
        lambda: service.disable_platform_live(db, project_id, platform_key, current_user_id=user.id)
    )


@router.post("/projects/{project_id}/full-auto-live/enable")
def enable_full_auto(
    project_id: int,
    payload: ConfirmationRequest,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Включить full-auto live (нужны project live + готовые площадки + подтверждение)."""
    return _run(
        lambda: service.enable_full_auto_live(
            db, project_id, payload.confirmation, current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/full-auto-live/disable")
def disable_full_auto(
    project_id: int, db: DbSession, service: ReadinessSvc, user: CurrentUser
) -> dict[str, Any]:
    """Выключить full-auto live."""
    return _run(lambda: service.disable_full_auto_live(db, project_id, current_user_id=user.id))


@router.get("/projects/{project_id}/effective/{platform_key}")
def effective_gate(
    project_id: int,
    platform_key: str,
    db: DbSession,
    service: ReadinessSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Эффективный live-гейт (project × platform). Глобальные флаги обязательны и не обходятся."""
    return _run(lambda: service.build_effective_live_gate(db, project_id, platform_key))
