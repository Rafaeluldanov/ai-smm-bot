"""API self-service подключений платформ (клиент заполняет API/ID в UI, без .env).

Все роуты под ``require_project_access`` (tenant-изоляция: чужой проект недоступен).
Секреты никогда не возвращаются — только маска/факт наличия. Проверка подключения
безопасна (read-only) и по умолчанию офлайн (без вызовов внешних API).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_guards import OptionalUser, require_project_access
from app.repositories import audit_log_repository
from app.schemas.platform_connection import PlatformConnectionUpsert
from app.services.audit_log_service import AuditLogService
from app.services.platform_connection_service import (
    PlatformConnectionError,
    PlatformConnectionService,
    get_platform_connection_service,
)

router = APIRouter(prefix="/projects", tags=["platform-connections"])

DbSession = Annotated[Session, Depends(get_db)]
ConnSvc = Annotated[PlatformConnectionService, Depends(get_platform_connection_service)]

_PREFIX = "/{project_id}/platform-connections"
_T = TypeVar("_T")


def _guard(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except PlatformConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(_PREFIX, dependencies=[Depends(require_project_access)])
def list_connections(project_id: int, db: DbSession, service: ConnSvc) -> list[dict[str, Any]]:
    """Все подключения платформ проекта (маскированные, без секретов)."""
    return service.list_connections(db, project_id)


@router.get(_PREFIX + "/{platform_key}/schema", dependencies=[Depends(require_project_access)])
def get_schema(project_id: int, platform_key: str, service: ConnSvc) -> dict[str, Any]:
    """Схема формы подключения платформы (поля/шаги/предупреждения)."""
    return service.get_schema(platform_key)


@router.get(_PREFIX + "/{platform_key}", dependencies=[Depends(require_project_access)])
def get_connection(
    project_id: int, platform_key: str, db: DbSession, service: ConnSvc
) -> dict[str, Any]:
    """Подключение платформы (маска) + схема формы. Секреты не возвращаются."""
    connection = service.get_connection(db, project_id, platform_key)
    return {"connection": connection, "schema": service.get_schema(platform_key)}


@router.post(_PREFIX + "/{platform_key}", dependencies=[Depends(require_project_access)])
def upsert_connection(
    project_id: int,
    platform_key: str,
    payload: PlatformConnectionUpsert,
    db: DbSession,
    service: ConnSvc,
    user: OptionalUser,
) -> dict[str, Any]:
    """Создать/обновить подключение. Секреты write-only; ответ маскирован."""
    return _guard(
        lambda: service.upsert_connection(
            db, project_id, platform_key, payload.model_dump(exclude_unset=True), current_user=user
        )
    )


@router.post(_PREFIX + "/{platform_key}/check", dependencies=[Depends(require_project_access)])
def check_connection(
    project_id: int, platform_key: str, db: DbSession, service: ConnSvc
) -> dict[str, Any]:
    """Безопасная проверка подключения (read-only, офлайн). Пишет last_check + аудит."""
    # http_client=None → без вызовов внешних API (офлайн-валидация полей и подсказки).
    return _guard(lambda: service.check_connection(db, project_id, platform_key, http_client=None))


@router.delete(_PREFIX + "/{platform_key}", dependencies=[Depends(require_project_access)])
def delete_connection(
    project_id: int, platform_key: str, db: DbSession, service: ConnSvc, user: OptionalUser
) -> dict[str, Any]:
    """Отключить платформу (soft delete). Секрет не раскрывается; пишется аудит."""
    removed = service.delete_connection(db, project_id, platform_key, current_user=user)
    return {"deleted": removed, "platform_key": platform_key}


@router.get(_PREFIX + "/{platform_key}/logs", dependencies=[Depends(require_project_access)])
def connection_logs(
    project_id: int, platform_key: str, db: DbSession, limit: int = 20
) -> list[dict[str, Any]]:
    """Последние действия проекта по платформе (из аудита, без секретов)."""
    entries = audit_log_repository.list_for_project(db, project_id, limit=max(1, min(limit, 100)))
    key = (platform_key or "").strip().lower()
    rows: list[dict[str, Any]] = []
    for entry in entries:
        meta = AuditLogService.sanitize_metadata(entry.entry_metadata)
        # Фильтр по платформе, если действие привязано к площадке (иначе — общий журнал).
        entry_platform = meta.get("platform") if isinstance(meta, dict) else None
        if entry_platform is not None and key not in ("", "all") and entry_platform != key:
            continue
        rows.append(
            {
                "id": entry.id,
                "action": entry.action,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
                "user_id": entry.user_id,
                "entity_type": entry.entity_type,
                "status": meta.get("status") if isinstance(meta, dict) else None,
                "platform": entry_platform,
            }
        )
    return rows
