"""Тесты middleware security headers (CSP, HSTS только для production/secure)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings

_PROD = Settings(_env_file=None, app_env="production")


def test_security_headers_present(client: TestClient) -> None:
    h = client.get("/health").headers
    assert h.get("x-content-type-options") == "nosniff"
    assert h.get("x-frame-options") == "DENY"
    assert h.get("referrer-policy") == "strict-origin-when-cross-origin"
    assert "geolocation=()" in (h.get("permissions-policy") or "")


def test_csp_present(client: TestClient) -> None:
    csp = client.get("/health").headers.get("content-security-policy") or ""
    assert "default-src 'self'" in csp
    assert "script-src" in csp


def test_hsts_absent_in_local(client: TestClient) -> None:
    assert "strict-transport-security" not in {k.lower() for k in client.get("/health").headers}


def test_hsts_present_in_production(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.security_middleware.get_settings", lambda: _PROD)
    h = client.get("/health").headers
    assert h.get("strict-transport-security") == "max-age=31536000; includeSubDomains"


def test_headers_not_duplicated(client: TestClient) -> None:
    raw = client.get("/health").headers
    # Один заголовок X-Frame-Options (setdefault не дублирует).
    assert sum(1 for k in raw if k.lower() == "x-frame-options") == 1
