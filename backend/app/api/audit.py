"""REST API аудит-лога: чтение событий аккаунта (tenant-изолировано).

Доступ — только участнику аккаунта (``require_account_member``). Секреты в аудит не
пишутся и не возвращаются. Чужой аккаунт → 404 (не раскрываем существование).
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_guards import require_account_member
from app.models.audit_log import AuditLogEntry
from app.schemas.audit import AuditLogEntryRead
from app.services.audit_log_service import AuditLogService, get_audit_log_service

router = APIRouter(prefix="/audit", tags=["audit"])

DbSession = Annotated[Session, Depends(get_db)]
AuditSvc = Annotated[AuditLogService, Depends(get_audit_log_service)]


@router.get(
    "/account/{account_id}",
    response_model=list[AuditLogEntryRead],
    dependencies=[Depends(require_account_member)],
)
def list_account_audit(
    account_id: int,
    db: DbSession,
    service: AuditSvc,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLogEntry]:
    """Аудит-лог аккаунта (свежие первыми). Только участнику аккаунта."""
    return service.list_for_account(db, account_id, limit, offset)
