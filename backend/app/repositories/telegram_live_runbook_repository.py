"""Репозиторий Telegram live runbook (runbook + попытки production-теста) — v0.6.3.

Публичные представления без секретов/токенов/сырых payload. Tenant isolation — на сервис/API-слое.
Репозиторий сам НЕ включает и НЕ меняет глобальные live-флаги.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.telegram_live_run_attempt import TelegramLiveRunAttempt
from app.models.telegram_live_runbook import TelegramLiveRunbook


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Runbook                                                                      #
# ---------------------------------------------------------------------------- #


def get_by_project(db: Session, project_id: int) -> TelegramLiveRunbook | None:
    """Runbook проекта (или None)."""
    stmt = select(TelegramLiveRunbook).where(TelegramLiveRunbook.project_id == project_id)
    return db.execute(stmt).scalars().first()


def get_or_create(
    db: Session, project_id: int, account_id: int | None = None
) -> TelegramLiveRunbook:
    """Вернуть runbook проекта или создать (status=draft)."""
    runbook = get_by_project(db, project_id)
    if runbook is not None:
        return runbook
    runbook = TelegramLiveRunbook(project_id=project_id, account_id=account_id, status="draft")
    db.add(runbook)
    db.commit()
    db.refresh(runbook)
    return runbook


def update_checklist(
    db: Session,
    runbook: TelegramLiveRunbook,
    *,
    checklist: dict[str, Any],
    blockers: list[Any],
    warnings: list[Any],
    flags: dict[str, bool],
    channel_id: str | None = None,
    channel_name: str | None = None,
) -> TelegramLiveRunbook:
    """Обновить чек-лист/флаги готовности runbook (+ last_check_at)."""
    runbook.checklist = checklist
    runbook.blockers = blockers
    runbook.warnings = warnings
    for key, value in flags.items():
        if hasattr(runbook, key):
            setattr(runbook, key, bool(value))
    if channel_id is not None:
        runbook.channel_id = channel_id
    if channel_name is not None:
        runbook.channel_name = channel_name
    runbook.last_check_at = _now()
    db.commit()
    db.refresh(runbook)
    return runbook


def update_status(db: Session, runbook: TelegramLiveRunbook, status: str) -> TelegramLiveRunbook:
    """Обновить статус runbook (draft/ready/blocked/enabled/paused)."""
    runbook.status = status
    db.commit()
    db.refresh(runbook)
    return runbook


def public_runbook_view(runbook: TelegramLiveRunbook) -> dict[str, Any]:
    """Безопасное представление runbook (без секретов)."""
    return {
        "id": runbook.id,
        "project_id": runbook.project_id,
        "account_id": runbook.account_id,
        "status": runbook.status,
        "channel_id": runbook.channel_id,
        "channel_name": runbook.channel_name,
        "connected": bool(runbook.connected),
        "media_proxy_ready": bool(runbook.media_proxy_ready),
        "calendar_ready": bool(runbook.calendar_ready),
        "readiness_ready": bool(runbook.readiness_ready),
        "monitoring_ready": bool(runbook.monitoring_ready),
        "balance_ready": bool(runbook.balance_ready),
        "last_check_at": runbook.last_check_at.isoformat() if runbook.last_check_at else None,
        "checklist": dict(runbook.checklist or {}),
        "blockers": list(runbook.blockers or []),
        "warnings": list(runbook.warnings or []),
        "created_at": runbook.created_at.isoformat() if runbook.created_at else None,
    }


# ---------------------------------------------------------------------------- #
# Run attempts                                                                 #
# ---------------------------------------------------------------------------- #


def create_attempt(db: Session, **fields: Any) -> TelegramLiveRunAttempt:
    """Создать попытку production-теста (preview/sending)."""
    fields.setdefault("started_at", _now())
    attempt = TelegramLiveRunAttempt(**fields)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def get_attempt_by_id(db: Session, attempt_id: int) -> TelegramLiveRunAttempt | None:
    """Попытка по id (или None)."""
    return db.get(TelegramLiveRunAttempt, attempt_id)


def update_attempt(
    db: Session, attempt: TelegramLiveRunAttempt, fields: dict[str, Any]
) -> TelegramLiveRunAttempt:
    """Обновить поля попытки."""
    for key, value in fields.items():
        setattr(attempt, key, value)
    db.commit()
    db.refresh(attempt)
    return attempt


def mark_published(
    db: Session,
    attempt: TelegramLiveRunAttempt,
    external_post_id: str | None = None,
    external_url: str | None = None,
    live_publish_attempt_id: int | None = None,
) -> TelegramLiveRunAttempt:
    """Отметить успешную production-публикацию."""
    return update_attempt(
        db,
        attempt,
        {
            "status": "published",
            "external_post_id": external_post_id,
            "external_url": external_url,
            "live_publish_attempt_id": live_publish_attempt_id,
            "finished_at": _now(),
        },
    )


def mark_failed(
    db: Session,
    attempt: TelegramLiveRunAttempt,
    error_message: str | None = None,
    status: str = "failed",
    live_publish_attempt_id: int | None = None,
) -> TelegramLiveRunAttempt:
    """Отметить неуспешную/заблокированную попытку (без раскрытия секретов)."""
    return update_attempt(
        db,
        attempt,
        {
            "status": status,
            "error_message": (error_message or "")[:500] or None,
            "live_publish_attempt_id": live_publish_attempt_id,
            "finished_at": _now(),
        },
    )


def list_attempts(
    db: Session, project_id: int, limit: int = 50, offset: int = 0
) -> list[TelegramLiveRunAttempt]:
    """Попытки проекта (свежие первыми)."""
    stmt = (
        select(TelegramLiveRunAttempt)
        .where(TelegramLiveRunAttempt.project_id == project_id)
        .order_by(TelegramLiveRunAttempt.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def public_attempt_view(attempt: TelegramLiveRunAttempt) -> dict[str, Any]:
    """Безопасное представление попытки (без секретов/токенов/сырых payload)."""
    return {
        "id": attempt.id,
        "project_id": attempt.project_id,
        "runbook_id": attempt.runbook_id,
        "post_id": attempt.post_id,
        "publication_id": attempt.publication_id,
        "live_publish_attempt_id": attempt.live_publish_attempt_id,
        "status": attempt.status,
        "confirmation_provided": bool(attempt.confirmation_text),
        "payload_preview": dict(attempt.payload_preview or {}),
        "external_post_id": attempt.external_post_id,
        "external_url": attempt.external_url,
        "error_message": attempt.error_message,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
    }
