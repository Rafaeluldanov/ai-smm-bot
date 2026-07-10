"""Тесты /health/security-readiness: local → 200, production misconfig → 503."""

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

_PROD_BAD = Settings(_env_file=None, app_env="production")  # без секрета
_PROD_OK = Settings(
    _env_file=None,
    app_env="production",
    auth_token_secret="prod-strong-secret-value-1234567",
    auth_allow_dev_token=False,
    auth_require_auth=True,
    auth_cookie_secure=True,
)


def test_local_readiness_ok_with_warnings(client: TestClient) -> None:
    r = client.get("/health/security-readiness")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "warning")
    assert body["errors"] == []
    assert "auth_token_secret_configured" in body["checks"]


def test_production_missing_secret_503(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _PROD_BAD
    try:
        r = client.get("/health/security-readiness")
        assert r.status_code == 503
        assert r.json()["status"] == "error"
        assert any("AUTH_TOKEN_SECRET" in e for e in r.json()["errors"])
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_production_configured_ok(client: TestClient) -> None:
    app.dependency_overrides[get_settings] = lambda: _PROD_OK
    try:
        r = client.get("/health/security-readiness")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.json()["errors"] == []
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_health_stays_public_and_simple(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
