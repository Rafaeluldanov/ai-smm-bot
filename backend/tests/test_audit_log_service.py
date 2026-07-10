"""Тесты сервиса аудит-лога: запись, чтение, санитизация, tenant-изоляция чтения."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.repositories import account_repository, user_repository
from app.services.audit_log_service import (
    ACTION_ANALYTICS_RUN,
    ACTION_USER_LOGIN,
    AuditLogService,
)


def _account(db: Session, email: str, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=email, password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    account_repository.create_membership(db, account.id, user.id, role="owner")
    return user, account


def test_record_and_list(db_session: Session) -> None:
    _user, account = _account(db_session, "a@e.com", "acc-a")
    svc = AuditLogService()
    svc.record(db_session, ACTION_USER_LOGIN, account_id=account.id, user_id=_user.id)
    svc.record(db_session, ACTION_ANALYTICS_RUN, account_id=account.id, metadata={"depth": "deep"})
    entries = svc.list_for_account(db_session, account.id)
    assert len(entries) == 2
    assert {e.action for e in entries} == {ACTION_USER_LOGIN, ACTION_ANALYTICS_RUN}


def test_metadata_sanitized(db_session: Session) -> None:
    _user, account = _account(db_session, "b@e.com", "acc-b")
    svc = AuditLogService()
    entry = svc.record(
        db_session,
        ACTION_ANALYTICS_RUN,
        account_id=account.id,
        metadata={"depth": "deep", "access_token": "vk1.SECRET", "note": "password=hunter2"},
    )
    assert entry is not None
    assert "access_token" not in entry.entry_metadata
    assert "hunter2" not in str(entry.entry_metadata)
    assert entry.entry_metadata["depth"] == "deep"


def test_disabled_audit_does_not_record(db_session: Session) -> None:
    _user, account = _account(db_session, "c@e.com", "acc-c")
    svc = AuditLogService(Settings(_env_file=None, audit_log_enabled=False))
    assert svc.record(db_session, ACTION_USER_LOGIN, account_id=account.id) is None
    assert svc.list_for_account(db_session, account.id) == []


def test_user_cannot_read_other_account_audit(client: TestClient, db_session: Session) -> None:
    ua, acc_a = _account(db_session, "owner-a@e.com", "own-a")
    ub, acc_b = _account(db_session, "owner-b@e.com", "own-b")
    AuditLogService().record(db_session, ACTION_USER_LOGIN, account_id=acc_a.id, user_id=ua.id)
    ha = {"Authorization": make_dev_token(ua.id)}
    hb = {"Authorization": make_dev_token(ub.id)}
    # Владелец видит свой аудит.
    assert client.get(f"/audit/account/{acc_a.id}", headers=ha).status_code == 200
    # Чужой — 404 (не раскрываем).
    assert client.get(f"/audit/account/{acc_a.id}", headers=hb).status_code == 404
