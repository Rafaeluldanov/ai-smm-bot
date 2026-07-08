"""Тесты сервиса аутентификации SaaS (offline, SQLite)."""

import pytest
from sqlalchemy.orm import Session

from app.core.security import parse_dev_token
from app.repositories import account_repository
from app.services.auth_service import (
    AuthError,
    AuthService,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
)


def _service() -> AuthService:
    return AuthService()


def test_register_creates_user_account_membership(db_session: Session) -> None:
    user, account = _service().register_user(
        db_session, "alice@example.com", "password123", "Alice", "Acme"
    )
    assert user.id is not None
    assert user.email == "alice@example.com"
    assert account.owner_user_id == user.id
    membership = account_repository.get_membership(db_session, account.id, user.id)
    assert membership is not None
    assert membership.role == "owner"
    assert membership.status == "active"


def test_password_hash_not_equal_raw(db_session: Session) -> None:
    user, _ = _service().register_user(db_session, "bob@example.com", "supersecret1")
    assert user.password_hash != "supersecret1"
    assert "supersecret1" not in user.password_hash
    assert user.password_hash.startswith("pbkdf2_sha256$")


def test_duplicate_email_rejected_case_insensitive(db_session: Session) -> None:
    service = _service()
    service.register_user(db_session, "carol@example.com", "password123")
    with pytest.raises(EmailAlreadyExistsError):
        service.register_user(db_session, "Carol@Example.com", "password123")


def test_authenticate_ok_and_fail(db_session: Session) -> None:
    service = _service()
    service.register_user(db_session, "dave@example.com", "password123")
    assert service.authenticate_user(db_session, "dave@example.com", "password123").email == (
        "dave@example.com"
    )
    with pytest.raises(InvalidCredentialsError):
        service.authenticate_user(db_session, "dave@example.com", "wrongpass")
    with pytest.raises(InvalidCredentialsError):
        service.authenticate_user(db_session, "missing@example.com", "password123")


def test_short_password_and_bad_email_rejected(db_session: Session) -> None:
    service = _service()
    with pytest.raises(AuthError):
        service.register_user(db_session, "eve@example.com", "short")
    with pytest.raises(AuthError):
        service.register_user(db_session, "notanemail", "password123")


def test_list_accounts_and_current_account(db_session: Session) -> None:
    service = _service()
    user, first = service.register_user(db_session, "frank@example.com", "password123")
    second = service.create_account_for_user(db_session, user, "Second Workspace")
    accounts = service.list_user_accounts(db_session, user.id)
    assert {a.id for a in accounts} == {first.id, second.id}
    assert service.get_current_account(db_session, user.id).id == first.id
    assert service.get_current_account(db_session, user.id, second.id).id == second.id
    assert service.get_current_account(db_session, user.id, 99999) is None


def test_dev_token_roundtrip(db_session: Session) -> None:
    service = _service()
    user, _ = service.register_user(db_session, "grace@example.com", "password123")
    token = service.issue_token(user)
    assert parse_dev_token(token) == user.id
    assert parse_dev_token("bogus.token") is None
    assert parse_dev_token(f"{user.id}.deadbeef") is None  # неверная подпись
