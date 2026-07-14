"""Репозиторий мониторинга live-автопилота (снимки + инциденты) — v0.6.1.

Изолирует доступ к ``live_autopilot_monitor_snapshots`` и ``live_autopilot_incidents``. Публичные
представления не содержат секретов/сырых токенов/payload. Tenant isolation — на сервис/API-слое.
Репозиторий сам НЕ включает и НЕ меняет глобальные live-флаги.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.live_autopilot_incident import LiveAutopilotIncident
from app.models.live_autopilot_monitor_snapshot import LiveAutopilotMonitorSnapshot


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Snapshots                                                                    #
# ---------------------------------------------------------------------------- #


def create_snapshot(db: Session, **fields: Any) -> LiveAutopilotMonitorSnapshot:
    """Создать снимок мониторинга."""
    snapshot = LiveAutopilotMonitorSnapshot(**fields)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_latest_snapshot_for_project(
    db: Session, project_id: int
) -> LiveAutopilotMonitorSnapshot | None:
    """Последний снимок проекта (или None)."""
    stmt = (
        select(LiveAutopilotMonitorSnapshot)
        .where(LiveAutopilotMonitorSnapshot.project_id == project_id)
        .order_by(LiveAutopilotMonitorSnapshot.id.desc())
    )
    return db.execute(stmt).scalars().first()


def list_snapshots_for_project(
    db: Session, project_id: int, limit: int = 50, offset: int = 0
) -> list[LiveAutopilotMonitorSnapshot]:
    """Снимки проекта (свежие первыми)."""
    stmt = (
        select(LiveAutopilotMonitorSnapshot)
        .where(LiveAutopilotMonitorSnapshot.project_id == project_id)
        .order_by(LiveAutopilotMonitorSnapshot.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def build_snapshot_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Короткая сводка по последнему снимку проекта."""
    latest = get_latest_snapshot_for_project(db, project_id)
    if latest is None:
        return {"has_snapshot": False, "health_status": "unknown"}
    return {
        "has_snapshot": True,
        "health_status": latest.health_status,
        "total_attempts": latest.total_attempts,
        "published_count": latest.published_count,
        "blocked_count": latest.blocked_count,
        "failed_count": latest.failed_count,
        "success_rate": latest.success_rate,
        "open_incident_count": latest.open_incident_count,
    }


def aggregate_attempts_for_window(
    db: Session,
    project_id: int,
    since: datetime,
    platform_key: str | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    """Агрегировать live-попытки проекта за окно наблюдения (без секретов/payload).

    Считает попытки со статусами published/failed/blocked/skipped за период ``since..now``,
    последние отметки времени и id последней попытки. Реальные отправки = published + failed.
    ``max_attempts`` (если задан) ограничивает выборку последними N попытками (по id убыв.).
    """
    from app.models.live_publish_attempt import LivePublishAttempt

    conditions = [
        LivePublishAttempt.project_id == project_id,
        LivePublishAttempt.created_at >= since,
    ]
    if platform_key:
        conditions.append(LivePublishAttempt.platform_key == platform_key)
    stmt = select(LivePublishAttempt).where(*conditions).order_by(LivePublishAttempt.id.desc())
    if max_attempts and max_attempts > 0:
        stmt = stmt.limit(max_attempts)
    rows = list(db.execute(stmt).scalars().all())

    def _stamp(attempt: LivePublishAttempt) -> datetime:
        return attempt.finished_at or attempt.created_at

    by_status: dict[str, int] = {}
    published = blocked = failed = skipped = 0
    last_attempt_id: int | None = rows[0].id if rows else None
    last_published_at: datetime | None = None
    last_failed_at: datetime | None = None
    last_blocked_at: datetime | None = None
    for attempt in rows:
        by_status[attempt.status] = by_status.get(attempt.status, 0) + 1
        # last_*_at считаем как максимум по времени завершения: id-порядок ≠ finished_at-порядок,
        # т.к. более ранняя попытка может завершиться позже (переменная задержка отправки).
        stamp = _stamp(attempt)
        if attempt.status == "published":
            published += 1
            last_published_at = (
                stamp if last_published_at is None else max(last_published_at, stamp)
            )
        elif attempt.status == "failed":
            failed += 1
            last_failed_at = stamp if last_failed_at is None else max(last_failed_at, stamp)
        elif attempt.status == "blocked":
            blocked += 1
            last_blocked_at = stamp if last_blocked_at is None else max(last_blocked_at, stamp)
        elif attempt.status == "skipped":
            skipped += 1

    total = len(rows)
    real_attempts = published + failed
    success_rate = round(published / real_attempts, 4) if real_attempts else 0.0
    failure_rate = round(failed / real_attempts, 4) if real_attempts else 0.0
    return {
        "total": total,
        "published": published,
        "blocked": blocked,
        "failed": failed,
        "skipped": skipped,
        "real_attempts": real_attempts,
        "success_rate": success_rate,
        "failure_rate": failure_rate,
        "by_status": by_status,
        "last_attempt_id": last_attempt_id,
        "last_published_at": last_published_at,
        "last_failed_at": last_failed_at,
        "last_blocked_at": last_blocked_at,
    }


def public_snapshot_view(snapshot: LiveAutopilotMonitorSnapshot) -> dict[str, Any]:
    """Безопасное представление снимка (без секретов)."""
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "account_id": snapshot.account_id,
        "platform_key": snapshot.platform_key,
        "health_status": snapshot.health_status,
        "period_start": snapshot.period_start.isoformat() if snapshot.period_start else None,
        "period_end": snapshot.period_end.isoformat() if snapshot.period_end else None,
        "total_attempts": snapshot.total_attempts,
        "published_count": snapshot.published_count,
        "blocked_count": snapshot.blocked_count,
        "failed_count": snapshot.failed_count,
        "skipped_count": snapshot.skipped_count,
        "success_rate": snapshot.success_rate,
        "failure_rate": snapshot.failure_rate,
        "last_attempt_id": snapshot.last_attempt_id,
        "last_published_at": snapshot.last_published_at.isoformat()
        if snapshot.last_published_at
        else None,
        "last_failed_at": snapshot.last_failed_at.isoformat() if snapshot.last_failed_at else None,
        "last_blocked_at": snapshot.last_blocked_at.isoformat()
        if snapshot.last_blocked_at
        else None,
        "open_incident_count": snapshot.open_incident_count,
        "critical_incident_count": snapshot.critical_incident_count,
        "balance_units": snapshot.balance_units,
        "approx_posts_left": snapshot.approx_posts_left,
        "project_live_enabled": bool(snapshot.project_live_enabled),
        "full_auto_live_enabled": bool(snapshot.full_auto_live_enabled),
        "platform_live_statuses": dict(snapshot.platform_live_statuses or {}),
        "readiness_status": dict(snapshot.readiness_status or {}),
        "blockers": list(snapshot.blockers or []),
        "warnings": list(snapshot.warnings or []),
        "summary": dict(snapshot.summary or {}),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


# ---------------------------------------------------------------------------- #
# Incidents                                                                    #
# ---------------------------------------------------------------------------- #


def create_incident(db: Session, **fields: Any) -> LiveAutopilotIncident:
    """Создать инцидент."""
    now = _now()
    fields.setdefault("first_seen_at", now)
    fields.setdefault("last_seen_at", now)
    incident = LiveAutopilotIncident(**fields)
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


def get_incident_by_id(db: Session, incident_id: int) -> LiveAutopilotIncident | None:
    """Инцидент по id (или None)."""
    return db.get(LiveAutopilotIncident, incident_id)


def find_open_incident(
    db: Session,
    project_id: int,
    incident_type: str,
    platform_key: str | None = None,
    dedup_seconds: int = 86400,
) -> LiveAutopilotIncident | None:
    """Найти открытый/подтверждённый инцидент того же типа в окне дедупликации."""
    since = _now() - timedelta(seconds=max(0, dedup_seconds))
    stmt = (
        select(LiveAutopilotIncident)
        .where(
            LiveAutopilotIncident.project_id == project_id,
            LiveAutopilotIncident.incident_type == incident_type,
            LiveAutopilotIncident.platform_key == platform_key,
            LiveAutopilotIncident.status.in_(("open", "acknowledged", "auto_paused")),
            LiveAutopilotIncident.last_seen_at >= since,
        )
        .order_by(LiveAutopilotIncident.id.desc())
    )
    return db.execute(stmt).scalars().first()


def create_or_increment_incident(
    db: Session,
    *,
    account_id: int | None,
    project_id: int,
    incident_type: str,
    severity: str,
    title: str,
    message: str,
    platform_key: str | None = None,
    dedup_seconds: int = 86400,
    **fields: Any,
) -> tuple[LiveAutopilotIncident, bool]:
    """Создать инцидент или инкрементировать существующий (дедуп по типу/площадке/окну).

    Возвращает (incident, created): created=True если создан новый.
    """
    existing = find_open_incident(db, project_id, incident_type, platform_key, dedup_seconds)
    if existing is not None:
        existing.occurrences += 1
        existing.last_seen_at = _now()
        # Эскалация серьёзности не понижается.
        if _severity_rank(severity) > _severity_rank(existing.severity):
            existing.severity = severity
        db.commit()
        db.refresh(existing)
        return existing, False
    incident = create_incident(
        db,
        account_id=account_id,
        project_id=project_id,
        platform_key=platform_key,
        incident_type=incident_type,
        severity=severity,
        title=title,
        message=message,
        **fields,
    )
    return incident, True


def list_incidents_for_project(
    db: Session, project_id: int, status: str | None = None, limit: int = 100, offset: int = 0
) -> list[LiveAutopilotIncident]:
    """Инциденты проекта (свежие первыми, с опциональным фильтром по статусу)."""
    stmt = select(LiveAutopilotIncident).where(LiveAutopilotIncident.project_id == project_id)
    if status is not None:
        stmt = stmt.where(LiveAutopilotIncident.status == status)
    stmt = stmt.order_by(LiveAutopilotIncident.id.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def list_open_incidents_for_project(db: Session, project_id: int) -> list[LiveAutopilotIncident]:
    """Открытые/подтверждённые/авто-паузнутые инциденты проекта."""
    stmt = (
        select(LiveAutopilotIncident)
        .where(
            LiveAutopilotIncident.project_id == project_id,
            LiveAutopilotIncident.status.in_(("open", "acknowledged", "auto_paused")),
        )
        .order_by(LiveAutopilotIncident.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def count_open_incidents(db: Session, project_id: int) -> tuple[int, int]:
    """(открытых, критических открытых) инцидентов проекта."""
    stmt = select(LiveAutopilotIncident.severity).where(
        LiveAutopilotIncident.project_id == project_id,
        LiveAutopilotIncident.status.in_(("open", "acknowledged", "auto_paused")),
    )
    severities = [s for (s,) in db.execute(stmt).all()]
    critical = sum(1 for s in severities if s == "critical")
    return len(severities), critical


def acknowledge_incident(
    db: Session, incident: LiveAutopilotIncident, user_id: int | None = None
) -> LiveAutopilotIncident:
    """Отметить инцидент подтверждённым."""
    incident.status = "acknowledged"
    incident.acknowledged_by_user_id = user_id
    incident.acknowledged_at = _now()
    db.commit()
    db.refresh(incident)
    return incident


def resolve_incident(
    db: Session, incident: LiveAutopilotIncident, user_id: int | None = None
) -> LiveAutopilotIncident:
    """Отметить инцидент решённым."""
    incident.status = "resolved"
    incident.resolved_by_user_id = user_id
    incident.resolved_at = _now()
    db.commit()
    db.refresh(incident)
    return incident


def ignore_incident(
    db: Session, incident: LiveAutopilotIncident, user_id: int | None = None
) -> LiveAutopilotIncident:
    """Отметить инцидент проигнорированным."""
    incident.status = "ignored"
    incident.ignored_by_user_id = user_id
    incident.ignored_at = _now()
    db.commit()
    db.refresh(incident)
    return incident


def mark_auto_paused(
    db: Session, incident: LiveAutopilotIncident, reason: str
) -> LiveAutopilotIncident:
    """Отметить инцидент как приведший к авто-паузе."""
    incident.status = "auto_paused"
    incident.auto_paused = True
    incident.auto_pause_reason = (reason or "")[:64] or None
    db.commit()
    db.refresh(incident)
    return incident


def public_incident_view(incident: LiveAutopilotIncident) -> dict[str, Any]:
    """Безопасное представление инцидента (без секретов)."""
    return {
        "id": incident.id,
        "project_id": incident.project_id,
        "account_id": incident.account_id,
        "platform_key": incident.platform_key,
        "incident_type": incident.incident_type,
        "status": incident.status,
        "severity": incident.severity,
        "title": incident.title,
        "message": incident.message,
        "source_entity_type": incident.source_entity_type,
        "source_entity_id": incident.source_entity_id,
        "live_publish_attempt_id": incident.live_publish_attempt_id,
        "post_id": incident.post_id,
        "publication_id": incident.publication_id,
        "schedule_run_id": incident.schedule_run_id,
        "occurrences": incident.occurrences,
        "first_seen_at": incident.first_seen_at.isoformat() if incident.first_seen_at else None,
        "last_seen_at": incident.last_seen_at.isoformat() if incident.last_seen_at else None,
        "acknowledged_at": incident.acknowledged_at.isoformat()
        if incident.acknowledged_at
        else None,
        "resolved_at": incident.resolved_at.isoformat() if incident.resolved_at else None,
        "auto_paused": bool(incident.auto_paused),
        "auto_pause_reason": incident.auto_pause_reason,
        "recommended_action": incident.recommended_action,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
    }


def _severity_rank(severity: str) -> int:
    return {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 2)
