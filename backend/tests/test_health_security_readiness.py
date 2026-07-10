"""Тесты /health/security-readiness (v0.3.3 shape): local → 200, prod misconfig → 503."""

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_PROD_BAD = Settings(_env_file=None, app_env="production")  # без секрета/флагов
_PROD_OK = Settings(
    _env_file=None,
    app_env="production",
    auth_token_secret="prod-strong-secret-value-1234567",
    auth_allow_dev_token=False,
    auth_require_auth=True,
    auth_cookie_secure=True,
    csrf_protection_enabled=True,
    rate_limit_enabled=True,
)


def test_local_readiness_ok_with_warnings(client: TestClient) -> None:
    r = client.get("/health/security-readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "warning")
    assert body["environment"] == "local"
    assert body["production_ready"] is True
    assert body["errors"] == []
    # checks — список объектов key/ok/severity/message.
    keys = {c["key"] for c in body["checks"]}
    assert "auth_secret_configured" in keys
    for c in body["checks"]:
        assert set(c) >= {"key", "ok", "severity", "message"}


def test_production_missing_secret_503(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _PROD_BAD
    try:
        r = client.get("/health/security-readiness")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "error"
        assert body["environment"] == "production"
        assert body["production_ready"] is False
        assert any("AUTH_TOKEN_SECRET" in e for e in body["errors"])
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_production_dev_token_enabled_503(client: TestClient) -> None:
    bad = Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="prod-strong-secret-value-1234567",
        auth_allow_dev_token=True,  # недопустимо в production
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )
    app.dependency_overrides[get_settings] = lambda: bad
    try:
        r = client.get("/health/security-readiness")
        assert r.status_code == 503
        assert any("AUTH_ALLOW_DEV_TOKEN" in e for e in r.json()["errors"])
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_production_configured_ok(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _PROD_OK
    try:
        r = client.get("/health/security-readiness")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["production_ready"] is True
        assert body["errors"] == []
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_readiness_does_not_leak_secrets(client: TestClient) -> None:
    ok = Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="SUPER-SECRET-PROD-VALUE-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )
    app.dependency_overrides[get_settings] = lambda: ok
    try:
        assert (
            "SUPER-SECRET-PROD-VALUE-1234567" not in client.get("/health/security-readiness").text
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_health_stays_public_and_simple(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
