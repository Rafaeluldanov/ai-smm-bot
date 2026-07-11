"""API фонового scheduler-worker: статус, безопасный tick (dry/create-drafts), lease.

Живой публикации нет: worker создаёт только draft/needs_review. Секретов/токенов в
ответах нет. В production операции требуют аутентифицированного суперпользователя; в
local разрешены (dev-token) для отладки.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_guards import OptionalUser, SettingsDep
from app.models.user import User
from app.repositories import scheduler_worker_repository
from app.services.scheduler_worker_service import (
    SchedulerWorkerService,
    get_scheduler_worker_service,
)

router = APIRouter(prefix="/scheduler-worker", tags=["scheduler-worker"])

DbSession = Annotated[Session, Depends(get_db)]
WorkerSvc = Annotated[SchedulerWorkerService, Depends(get_scheduler_worker_service)]

_AUTH_REQUIRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация"
)
_FORBIDDEN = HTTPException(
    status_code=status.HTTP_403_FORBIDDEN, detail="Нужны права суперпользователя"
)


class WorkerTickRequest(BaseModel):
    """Параметры запуска одного тика worker-а."""

    force: bool = False
    platform_key: str | None = None
    account_id: int | None = None
    project_id: int | None = None


def require_status_reader(user: OptionalUser, settings: SettingsDep) -> User | None:
    """Чтение статуса: в production нужен авторизованный пользователь; в local — свободно."""
    if settings.is_production and user is None:
        raise _AUTH_REQUIRED
    return user


def require_worker_operator(user: OptionalUser, settings: SettingsDep) -> User | None:
    """Операции worker-а: в production — суперпользователь; в local — разрешено (dev)."""
    if settings.is_production:
        if user is None:
            raise _AUTH_REQUIRED
        if not user.is_superuser:
            raise _FORBIDDEN
    return user


@router.get("/status")
def worker_status(
    db: DbSession,
    service: WorkerSvc,
    _reader: Annotated[User | None, Depends(require_status_reader)],
) -> dict[str, Any]:
    """Состояние worker-а: enabled/dry_run/interval/lease/warnings (без секретов)."""
    return service.status(db)


@router.get("/leases")
def worker_leases(
    db: DbSession, _reader: Annotated[User | None, Depends(require_status_reader)]
) -> list[dict[str, Any]]:
    """Текущие lease worker-а (без секретов)."""
    return [
        {
            "id": lease.id,
            "lease_key": lease.lease_key,
            "owner_id": lease.owner_id,
            "status": lease.status,
            "acquired_at": lease.acquired_at.isoformat() if lease.acquired_at else None,
            "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
            "heartbeat_at": lease.heartbeat_at.isoformat() if lease.heartbeat_at else None,
        }
        for lease in scheduler_worker_repository.list_leases(db)
    ]


@router.post("/tick-dry")
def worker_tick_dry(
    payload: WorkerTickRequest,
    db: DbSession,
    service: WorkerSvc,
    operator: Annotated[User | None, Depends(require_worker_operator)],
) -> dict[str, Any]:
    """Безопасный dry-run одного тика (без создания постов, без live)."""
    result = service.tick(
        db,
        owner_id=service.build_owner_id(),
        dry_run=True,
        force=True,
        platform_key=payload.platform_key,
        account_id=payload.account_id,
        project_id=payload.project_id,
    )
    return result.as_dict()


@router.post("/tick")
def worker_tick(
    payload: WorkerTickRequest,
    db: DbSession,
    service: WorkerSvc,
    settings: SettingsDep,
    operator: Annotated[User | None, Depends(require_worker_operator)],
) -> dict[str, Any]:
    """Один тик: создаёт draft/needs_review (если CREATE_DRAFTS=true). Live-публикации НЕТ.

    Если worker выключен и не передан ``force=true`` — 400 (защита от случайного запуска).
    """
    if not settings.scheduler_worker_enabled_effective and not payload.force:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Worker выключен (SCHEDULER_WORKER_ENABLED=false). Передайте force=true.",
        )
    result = service.tick(
        db,
        owner_id=service.build_owner_id(),
        dry_run=None,  # из настроек (create_drafts=false → dry-run)
        force=True,
        platform_key=payload.platform_key,
        account_id=payload.account_id,
        project_id=payload.project_id,
    )
    return result.as_dict()
