"""Репозиторий lease фонового scheduler-worker (DB-based lock).

Секретов не хранит. Все проверки времени — по переданному ``now`` (тестируемо).
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.scheduler_worker_lease import SchedulerWorkerLease


def _aware(value: datetime | None) -> datetime | None:
    """Привести datetime к aware UTC (SQLite может вернуть naive)."""
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def get_lease(db: Session, lease_key: str) -> SchedulerWorkerLease | None:
    """Вернуть lease по ключу (или None)."""
    return db.scalars(
        select(SchedulerWorkerLease).where(SchedulerWorkerLease.lease_key == lease_key)
    ).first()


def list_leases(db: Session) -> list[SchedulerWorkerLease]:
    """Все lease (свежие первыми)."""
    return list(db.scalars(select(SchedulerWorkerLease).order_by(SchedulerWorkerLease.id.desc())))


def _is_held_by_other(lease: SchedulerWorkerLease, owner_id: str, now: datetime) -> bool:
    """Занята ли активная не истёкшая lease другим владельцем."""
    if lease.status != "active":
        return False
    expires = _aware(lease.expires_at)
    if expires is not None and expires <= now:
        return False  # истекла → свободна
    return lease.owner_id != owner_id


def acquire_lease(
    db: Session,
    lease_key: str,
    owner_id: str,
    ttl_seconds: int,
    now: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Захватить/продлить lease. False — если активна и держится другим владельцем."""
    now = now or datetime.now(UTC)
    expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
    lease = get_lease(db, lease_key)
    if lease is not None and _is_held_by_other(lease, owner_id, now):
        return False
    if lease is None:
        lease = SchedulerWorkerLease(lease_key=lease_key, owner_id=owner_id)
        db.add(lease)
    lease.owner_id = owner_id
    lease.status = "active"
    lease.acquired_at = now
    lease.expires_at = expires_at
    lease.heartbeat_at = now
    lease.released_at = None
    if metadata is not None:
        lease.lease_metadata = metadata
    db.commit()
    db.refresh(lease)
    return True


def heartbeat_lease(
    db: Session, lease_key: str, owner_id: str, ttl_seconds: int, now: datetime | None = None
) -> bool:
    """Продлить lease текущего владельца (heartbeat). False — если чужая/нет."""
    now = now or datetime.now(UTC)
    lease = get_lease(db, lease_key)
    if lease is None or lease.status != "active" or lease.owner_id != owner_id:
        return False
    lease.heartbeat_at = now
    lease.expires_at = now + timedelta(seconds=max(1, int(ttl_seconds)))
    db.commit()
    return True


def release_lease(db: Session, lease_key: str, owner_id: str, now: datetime | None = None) -> bool:
    """Освободить lease (только владельцем). Повторный release не падает."""
    now = now or datetime.now(UTC)
    lease = get_lease(db, lease_key)
    if lease is None or lease.owner_id != owner_id:
        return False
    lease.status = "released"
    lease.released_at = now
    db.commit()
    return True


def cleanup_expired_leases(db: Session, now: datetime | None = None) -> int:
    """Пометить активные истёкшие lease как expired. Возврат — количество."""
    now = now or datetime.now(UTC)
    leases = list(
        db.scalars(select(SchedulerWorkerLease).where(SchedulerWorkerLease.status == "active"))
    )
    changed = 0
    for lease in leases:
        expires = _aware(lease.expires_at)
        if expires is not None and expires <= now:
            lease.status = "expired"
            changed += 1
    if changed:
        db.commit()
    return changed
