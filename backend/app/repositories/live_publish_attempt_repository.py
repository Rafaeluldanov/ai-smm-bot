"""Репозиторий попыток live-публикации (live rollout journal) — v0.6.0.

Изолирует доступ к ``live_publish_attempts``. Публичное представление не содержит секретов/сырых
токенов/внутренних путей. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.live_publish_attempt import LivePublishAttempt


def _now() -> datetime:
    return datetime.now(UTC)


def create_attempt(db: Session, **fields: Any) -> LivePublishAttempt:
    """Создать запись попытки публикации."""
    attempt = LivePublishAttempt(**fields)
    db.add(attempt)
    db.commit()
    db.refresh(attempt)
    return attempt


def get_attempt_by_id(db: Session, attempt_id: int) -> LivePublishAttempt | None:
    """Попытка по id (или None)."""
    return db.get(LivePublishAttempt, attempt_id)


def get_by_idempotency_key(db: Session, key: str) -> LivePublishAttempt | None:
    """Попытка по idempotency-ключу (или None)."""
    if not key:
        return None
    stmt = select(LivePublishAttempt).where(LivePublishAttempt.idempotency_key == key)
    return db.execute(stmt).scalars().first()


def list_attempts_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[LivePublishAttempt]:
    """Попытки проекта (свежие первыми)."""
    stmt = (
        select(LivePublishAttempt)
        .where(LivePublishAttempt.project_id == project_id)
        .order_by(LivePublishAttempt.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def list_attempts_for_post(db: Session, post_id: int) -> list[LivePublishAttempt]:
    """Попытки по посту (свежие первыми)."""
    stmt = (
        select(LivePublishAttempt)
        .where(LivePublishAttempt.post_id == post_id)
        .order_by(LivePublishAttempt.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def list_recent_attempts(db: Session, limit: int = 50) -> list[LivePublishAttempt]:
    """Недавние попытки по всем проектам (для админ-мониторинга)."""
    stmt = select(LivePublishAttempt).order_by(LivePublishAttempt.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def update_attempt(
    db: Session, attempt: LivePublishAttempt, fields: dict[str, Any]
) -> LivePublishAttempt:
    """Обновить произвольные поля попытки."""
    for key, value in fields.items():
        setattr(attempt, key, value)
    db.commit()
    db.refresh(attempt)
    return attempt


def mark_blocked(
    db: Session, attempt: LivePublishAttempt, blockers: list[dict[str, Any]]
) -> LivePublishAttempt:
    """Отметить попытку заблокированной (реального вызова не было, списания нет)."""
    return update_attempt(
        db,
        attempt,
        {
            "status": "blocked",
            "mode": "live_blocked",
            "live_attempted": False,
            "blockers": blockers,
            "finished_at": _now(),
        },
    )


def mark_attempted(db: Session, attempt: LivePublishAttempt) -> LivePublishAttempt:
    """Отметить, что реальная попытка отправки началась."""
    return update_attempt(
        db, attempt, {"status": "attempted", "live_attempted": True, "started_at": _now()}
    )


def mark_published(
    db: Session,
    attempt: LivePublishAttempt,
    external_post_id: str | None = None,
    external_url: str | None = None,
    response_summary: dict[str, Any] | None = None,
) -> LivePublishAttempt:
    """Отметить успешную live-публикацию."""
    return update_attempt(
        db,
        attempt,
        {
            "status": "published",
            "live_attempted": True,
            "external_post_id": external_post_id,
            "external_url": external_url,
            "response_summary": response_summary or {},
            "finished_at": _now(),
        },
    )


def mark_failed(
    db: Session,
    attempt: LivePublishAttempt,
    error_message: str | None = None,
    response_summary: dict[str, Any] | None = None,
) -> LivePublishAttempt:
    """Отметить неуспешную live-попытку (без раскрытия секретов)."""
    return update_attempt(
        db,
        attempt,
        {
            "status": "failed",
            "live_attempted": True,
            "error_message": (error_message or "")[:500] or None,
            "response_summary": response_summary or {},
            "finished_at": _now(),
        },
    )


def build_project_attempt_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка попыток проекта (счётчики по статусам + последняя попытка)."""
    stmt = (
        select(LivePublishAttempt.status, func.count())
        .where(LivePublishAttempt.project_id == project_id)
        .group_by(LivePublishAttempt.status)
    )
    counts = {status: int(count) for status, count in db.execute(stmt).all()}
    latest = list_attempts_for_project(db, project_id, limit=1)
    return {
        "total": sum(counts.values()),
        "by_status": counts,
        "published": counts.get("published", 0),
        "blocked": counts.get("blocked", 0),
        "failed": counts.get("failed", 0),
        "last_attempt": public_attempt_view(latest[0]) if latest else None,
    }


def public_attempt_view(attempt: LivePublishAttempt) -> dict[str, Any]:
    """Безопасное представление попытки (без секретов/токенов/внутренних путей)."""
    return {
        "id": attempt.id,
        "project_id": attempt.project_id,
        "account_id": attempt.account_id,
        "platform_key": attempt.platform_key,
        "post_id": attempt.post_id,
        "publication_id": attempt.publication_id,
        "schedule_run_id": attempt.schedule_run_id,
        "trigger": attempt.trigger,
        "mode": attempt.mode,
        "status": attempt.status,
        "global_live_enabled": bool(attempt.global_live_enabled),
        "project_live_enabled": bool(attempt.project_live_enabled),
        "platform_live_enabled": bool(attempt.platform_live_enabled),
        "full_auto_live_enabled": bool(attempt.full_auto_live_enabled),
        "readiness_ready": bool(attempt.readiness_ready),
        "balance_ok": bool(attempt.balance_ok),
        "live_attempted": bool(attempt.live_attempted),
        "external_post_id": attempt.external_post_id,
        "external_url": attempt.external_url,
        "request_summary": dict(attempt.request_summary or {}),
        "response_summary": dict(attempt.response_summary or {}),
        "blockers": list(attempt.blockers or []),
        "warnings": list(attempt.warnings or []),
        "error_message": attempt.error_message,
        "started_at": attempt.started_at.isoformat() if attempt.started_at else None,
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
        "created_at": attempt.created_at.isoformat() if attempt.created_at else None,
    }
