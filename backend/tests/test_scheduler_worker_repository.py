"""Тесты DB-lease фонового scheduler-worker."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.repositories import scheduler_worker_repository as repo

_KEY = "scheduler-worker"
_NOW = datetime(2026, 7, 13, 12, 0, tzinfo=UTC)


def test_acquire_empty_ok(db_session: Session) -> None:
    assert repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW) is True
    lease = repo.get_lease(db_session, _KEY)
    assert lease.status == "active" and lease.owner_id == "owner-a"


def test_second_owner_blocked(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW)
    # Другой владелец при активной не истёкшей lease — отказ.
    assert repo.acquire_lease(db_session, _KEY, "owner-b", 300, now=_NOW) is False


def test_expired_lease_can_be_acquired(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 60, now=_NOW)
    later = _NOW + timedelta(seconds=120)  # lease истекла
    assert repo.acquire_lease(db_session, _KEY, "owner-b", 300, now=later) is True
    assert repo.get_lease(db_session, _KEY).owner_id == "owner-b"


def test_same_owner_reacquire_ok(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW)
    assert repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW) is True


def test_heartbeat_extends_lease(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 60, now=_NOW)
    before = repo.get_lease(db_session, _KEY).expires_at
    later = _NOW + timedelta(seconds=30)
    assert repo.heartbeat_lease(db_session, _KEY, "owner-a", 300, now=later) is True
    after = repo.get_lease(db_session, _KEY).expires_at
    assert after > before


def test_heartbeat_wrong_owner_fails(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW)
    assert repo.heartbeat_lease(db_session, _KEY, "owner-b", 300, now=_NOW) is False


def test_release_by_owner(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW)
    assert repo.release_lease(db_session, _KEY, "owner-a", now=_NOW) is True
    assert repo.get_lease(db_session, _KEY).status == "released"
    # Повторный release не падает.
    assert repo.release_lease(db_session, _KEY, "owner-a", now=_NOW) is True


def test_wrong_owner_cannot_release(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 300, now=_NOW)
    assert repo.release_lease(db_session, _KEY, "owner-b", now=_NOW) is False
    assert repo.get_lease(db_session, _KEY).status == "active"


def test_cleanup_expired(db_session: Session) -> None:
    repo.acquire_lease(db_session, _KEY, "owner-a", 60, now=_NOW)
    later = _NOW + timedelta(seconds=120)
    assert repo.cleanup_expired_leases(db_session, now=later) == 1
    assert repo.get_lease(db_session, _KEY).status == "expired"
