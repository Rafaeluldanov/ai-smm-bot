"""Тесты admin-скриптов: create-user, grant-role, audit-export (без утечки секретов)."""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.repositories import account_repository, audit_log_repository, user_repository
from app.scripts.admin_create_user import create_user_and_account
from app.scripts.admin_grant_role import grant_role
from app.scripts.audit_export import export_rows
from app.services.audit_log_service import AuditLogService


def test_create_user_and_account(db_session: Session) -> None:
    user_id, account_id = create_user_and_account(
        db_session, email="admin@e.com", password="password123", account_name="Workspace"
    )
    assert user_id > 0 and account_id is not None
    user = user_repository.get_user_by_id(db_session, user_id)
    assert user is not None and user.email == "admin@e.com"
    # Пароль хранится хешем (не в открытом виде).
    assert user.password_hash != "password123"
    assert "pbkdf2" in user.password_hash


def test_grant_role_creates_and_updates(db_session: Session) -> None:
    uid, aid = create_user_and_account(db_session, email="r@e.com", password="password123")
    other = user_repository.create_user(db_session, email="member@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="Acc", slug="acc-x", owner_user_id=uid
    )
    created = grant_role(db_session, account.id, other.id, "admin")
    assert created is True
    membership = account_repository.get_membership(db_session, account.id, other.id)
    assert membership is not None and membership.role == "admin"
    # Повторно — обновление, не создание.
    assert grant_role(db_session, account.id, other.id, "viewer") is False
    assert account_repository.get_membership(db_session, account.id, other.id).role == "viewer"


def test_audit_export_sanitizes(db_session: Session, tmp_path: Path) -> None:
    user = user_repository.create_user(db_session, email="a@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="A", slug="a", owner_user_id=user.id
    )
    AuditLogService().record(
        db_session,
        "user.login",
        account_id=account.id,
        user_id=user.id,
        metadata={"note": "ok", "access_token": "vk1.SECRETVALUE", "password": "pw"},
    )
    entries = audit_log_repository.list_for_account(db_session, account.id)
    from app.scripts.audit_export import _row

    rows = [_row(e) for e in entries]
    out = tmp_path / "audit.jsonl"
    export_rows(rows, str(out), "jsonl")
    text = out.read_text(encoding="utf-8")
    assert "SECRETVALUE" not in text
    assert "access_token" not in text
    assert "user.login" in text
    # JSONL валиден.
    for line in text.strip().splitlines():
        json.loads(line)
