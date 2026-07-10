"""Тесты production-ограничений auth: dev-токен, обязательный секрет, cookie-auth."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import Settings, get_settings, production_security_errors
from app.core.security import make_dev_token
from app.main import app
from app.repositories import account_repository, user_repository
from app.services.auth_token_service import AuthTokenService

_PROD = Settings(
    _env_file=None,
    app_env="production",
    auth_token_secret="prod-strong-secret-value-1234567",
    auth_allow_dev_token=False,
    auth_require_auth=True,
    auth_cookie_secure=True,
)
_PROD_COOKIE = Settings(
    _env_file=None,
    app_env="production",
    auth_token_secret="prod-strong-secret-value-1234567",
    auth_allow_dev_token=False,
    auth_require_auth=True,
    auth_cookie_secure=True,
    auth_cookie_auth_enabled=True,
)


def _user(db: Session, email: str) -> int:
    u = user_repository.create_user(db, email=email, password_hash="x")
    account_repository.create_account(db, name="A", slug=email.split("@")[0], owner_user_id=u.id)
    return u.id


def test_dev_token_accepted_in_local(client: TestClient, db_session: Session) -> None:
    uid = _user(db_session, "dev-local@e.com")
    r = client.get("/auth/me", headers={"Authorization": make_dev_token(uid)})
    assert r.status_code == 200


def test_dev_token_rejected_in_production(client: TestClient, db_session: Session) -> None:
    uid = _user(db_session, "dev-prod@e.com")
    app.dependency_overrides[get_settings] = lambda: _PROD
    r = client.get("/auth/me", headers={"Authorization": make_dev_token(uid)})
    assert r.status_code == 401


def test_anonymous_rejected_in_production(client: TestClient, db_session: Session) -> None:
    _user(db_session, "anon-prod@e.com")
    app.dependency_overrides[get_settings] = lambda: _PROD
    assert client.get("/auth/me").status_code == 401


def test_cookie_access_token_works(client: TestClient, db_session: Session) -> None:
    uid = _user(db_session, "cookie@e.com")
    app.dependency_overrides[get_settings] = lambda: _PROD_COOKIE
    access = AuthTokenService(_PROD_COOKIE).issue_access_token(uid, [])
    client.cookies.set("botfleet_session", access)
    r = client.get("/auth/me")  # без Authorization — только cookie
    assert r.status_code == 200


def test_production_requires_auth_token_secret() -> None:
    # production без секрета → фатальная ошибка (падение старта / 503 readiness).
    missing = Settings(_env_file=None, app_env="production")
    assert not missing.auth_token_secret_configured
    assert production_security_errors(missing)
    # с надёжным секретом и правильными флагами → нет фатальных ошибок.
    assert production_security_errors(_PROD) == []


def test_default_dev_secret_not_configured() -> None:
    weak = Settings(_env_file=None, app_env="production", auth_token_secret="change-me")
    assert not weak.auth_token_secret_configured
    assert production_security_errors(weak)


def test_create_app_fails_in_production_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.setattr(
        main, "get_settings", lambda: Settings(_env_file=None, app_env="production")
    )
    with pytest.raises(RuntimeError):
        main.create_app()


def _override_db(session_factory):  # noqa: ANN001, ANN202
    def _get():  # noqa: ANN202
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    return _get


@pytest.fixture(autouse=True)
def _ensure_db_override(session_factory):  # noqa: ANN001, ANN201
    # Тесты выше меняют get_settings; get_db остаётся на тестовую сессию.
    app.dependency_overrides[get_db] = _override_db(session_factory)
    yield
    app.dependency_overrides.clear()
