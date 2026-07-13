"""Репозиторий логов входящих Telegram-обновлений (webhook/polling sandbox) — v0.5.5.

Изолирует доступ к ``notification_telegram_update_logs``. Публичное представление (``public_*``)
НИКОГДА не содержит сырой chat_id / telegram_user_id / verification token / bot token / webhook
secret. Tenant isolation обеспечивается на сервисном/API-слое.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.notification_telegram_update_log import NotificationTelegramUpdateLog


def create_update_log(db: Session, **fields: Any) -> NotificationTelegramUpdateLog:
    """Создать запись входящего апдейта (без сырых id/токенов в полях)."""
    log = NotificationTelegramUpdateLog(**fields)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_by_id(db: Session, log_id: int) -> NotificationTelegramUpdateLog | None:
    """Запись апдейта по id (или None)."""
    return db.get(NotificationTelegramUpdateLog, log_id)


def get_by_update_id(
    db: Session, update_id: int, binding_id: int | None = None
) -> NotificationTelegramUpdateLog | None:
    """Найти уже обработанный апдейт по Telegram update_id (для дедупликации)."""
    if update_id is None:
        return None
    stmt = select(NotificationTelegramUpdateLog).where(
        NotificationTelegramUpdateLog.update_id == update_id
    )
    if binding_id is not None:
        stmt = stmt.where(NotificationTelegramUpdateLog.binding_id == binding_id)
    stmt = stmt.order_by(NotificationTelegramUpdateLog.id.desc())
    return db.execute(stmt).scalars().first()


def list_for_user(
    db: Session, user_id: int, limit: int = 50
) -> list[NotificationTelegramUpdateLog]:
    """Апдейты пользователя (свежие первыми)."""
    stmt = (
        select(NotificationTelegramUpdateLog)
        .where(NotificationTelegramUpdateLog.user_id == user_id)
        .order_by(NotificationTelegramUpdateLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_for_project(
    db: Session, project_id: int, limit: int = 100
) -> list[NotificationTelegramUpdateLog]:
    """Апдейты проекта (свежие первыми)."""
    stmt = (
        select(NotificationTelegramUpdateLog)
        .where(NotificationTelegramUpdateLog.project_id == project_id)
        .order_by(NotificationTelegramUpdateLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_recent(db: Session, limit: int = 50) -> list[NotificationTelegramUpdateLog]:
    """Недавние апдейты (свежие первыми) — для sandbox-дашборда."""
    stmt = (
        select(NotificationTelegramUpdateLog)
        .order_by(NotificationTelegramUpdateLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def _finalize(
    db: Session,
    log: NotificationTelegramUpdateLog,
    status: str,
    now: datetime,
    error: str | None = None,
    result_metadata: dict[str, Any] | None = None,
    binding_id: int | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    project_id: int | None = None,
) -> NotificationTelegramUpdateLog:
    log.status = status
    log.processed_at = now
    if error is not None:
        log.error_message = error[:512]
    if result_metadata is not None:
        log.result_metadata = result_metadata
    if binding_id is not None:
        log.binding_id = binding_id
    if user_id is not None:
        log.user_id = user_id
    if account_id is not None:
        log.account_id = account_id
    if project_id is not None:
        log.project_id = project_id
    db.commit()
    db.refresh(log)
    return log


def mark_processed(
    db: Session,
    log: NotificationTelegramUpdateLog,
    now: datetime,
    result_metadata: dict[str, Any] | None = None,
) -> NotificationTelegramUpdateLog:
    """Отметить апдейт обработанным (processed)."""
    return _finalize(db, log, "processed", now, result_metadata=result_metadata)


def mark_ignored(
    db: Session,
    log: NotificationTelegramUpdateLog,
    now: datetime,
    reason: str | None = None,
) -> NotificationTelegramUpdateLog:
    """Отметить апдейт проигнорированным (ignored) — неизвестный тип/команда."""
    return _finalize(db, log, "ignored", now, result_metadata={"reason": reason} if reason else {})


def mark_failed(
    db: Session,
    log: NotificationTelegramUpdateLog,
    now: datetime,
    error: str | None = None,
) -> NotificationTelegramUpdateLog:
    """Отметить апдейт неуспешным (failed); текст ошибки уже санитизирован."""
    return _finalize(db, log, "failed", now, error=error or "update processing failed")


def mark_verified_binding(
    db: Session,
    log: NotificationTelegramUpdateLog,
    now: datetime,
    binding_id: int | None = None,
    user_id: int | None = None,
    account_id: int | None = None,
    project_id: int | None = None,
    result_metadata: dict[str, Any] | None = None,
) -> NotificationTelegramUpdateLog:
    """Отметить, что апдейт верифицировал привязку (verified_binding)."""
    return _finalize(
        db,
        log,
        "verified_binding",
        now,
        result_metadata=result_metadata,
        binding_id=binding_id,
        user_id=user_id,
        account_id=account_id,
        project_id=project_id,
    )


def public_update_view(log: NotificationTelegramUpdateLog) -> dict[str, Any]:
    """Безопасное представление апдейта (без сырого chat_id / токена / bot token / secret)."""
    return {
        "id": log.id,
        "project_id": log.project_id,
        "user_id": log.user_id,
        "binding_id": log.binding_id,
        "update_id": log.update_id,
        "update_type": log.update_type,
        "status": log.status,
        "command": log.command,
        "username": log.username,
        "text_preview": log.text_preview,
        "error_message": log.error_message,
        "received_at": log.received_at.isoformat() if log.received_at else None,
        "processed_at": log.processed_at.isoformat() if log.processed_at else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def dashboard_summary(logs: list[NotificationTelegramUpdateLog]) -> dict[str, int]:
    """Сводка по статусам входящих апдейтов (для дашборда)."""
    summary: dict[str, int] = {"total": len(logs)}
    for log in logs:
        summary[log.status] = summary.get(log.status, 0) + 1
    return summary


def count_by_status(db: Session, project_id: int | None = None) -> dict[str, int]:
    """Счётчики апдейтов по статусам (опционально по проекту)."""
    stmt = select(
        NotificationTelegramUpdateLog.status, func.count(NotificationTelegramUpdateLog.id)
    )
    if project_id is not None:
        stmt = stmt.where(NotificationTelegramUpdateLog.project_id == project_id)
    stmt = stmt.group_by(NotificationTelegramUpdateLog.status)
    return {status: int(count) for status, count in db.execute(stmt).all()}
