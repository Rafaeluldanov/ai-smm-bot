"""Репозиторий аудит-лога."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLogEntry


def create_entry(db: Session, **fields: Any) -> AuditLogEntry:
    """Создать запись аудита."""
    entry = AuditLogEntry(**fields)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_for_account(
    db: Session, account_id: int, limit: int = 100, offset: int = 0
) -> list[AuditLogEntry]:
    """Записи аудита аккаунта (свежие первыми)."""
    stmt = (
        select(AuditLogEntry)
        .where(AuditLogEntry.account_id == account_id)
        .order_by(AuditLogEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[AuditLogEntry]:
    """Записи аудита проекта (свежие первыми)."""
    stmt = (
        select(AuditLogEntry)
        .where(AuditLogEntry.project_id == project_id)
        .order_by(AuditLogEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())
