"""Тесты CSRF-защиты (double-submit cookie) для cookie-auth."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings

_CSRF_ON = Settings(_env_file=None, csrf_protection_enabled=True)
_COOKIE = "csrf-value-abc"


@pytest.fixture
def csrf_enabled(monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    """Включить CSRF в middleware и поставить csrf-cookie на клиента."""
    monkeypatch.setattr("app.api.security_middleware.get_settings", lambda: _CSRF_ON)
    yield


def test_csrf_disabled_local_post_ok(client: TestClient) -> None:
    # CSRF выключен по умолчанию — POST без заголовка не блокируется CSRF.
    r = client.post("/saas/onboarding/apply", json={})
    assert r.status_code != 403


def test_csrf_enabled_missing_header_403(client: TestClient, csrf_enabled) -> None:  # noqa: ANN001
    client.cookies.set("botfleet_csrf", _COOKIE)
    r = client.post("/saas/onboarding/apply", json={})
    assert r.status_code == 403
    assert "CSRF" in r.json()["detail"]


def test_csrf_enabled_matching_header_ok(client: TestClient, csrf_enabled) -> None:  # noqa: ANN001
    client.cookies.set("botfleet_csrf", _COOKIE)
    r = client.post("/saas/onboarding/apply", json={}, headers={"X-CSRF-Token": _COOKIE})
    assert r.status_code != 403  # CSRF пройден (дальше — валидация тела)


def test_csrf_get_exempt(client: TestClient, csrf_enabled) -> None:  # noqa: ANN001
    client.cookies.set("botfleet_csrf", _COOKIE)
    r = client.get("/saas/accounts/1/projects")
    assert r.status_code != 403  # безопасный метод не проверяется


def test_csrf_bearer_exempt(client: TestClient, csrf_enabled) -> None:  # noqa: ANN001
    client.cookies.set("botfleet_csrf", _COOKIE)
    r = client.post("/saas/onboarding/apply", json={}, headers={"Authorization": "1.deadbeef"})
    assert r.status_code != 403  # Bearer-клиент освобождён от CSRF


def test_csrf_webhook_exempt(client: TestClient, csrf_enabled) -> None:  # noqa: ANN001
    client.cookies.set("botfleet_csrf", _COOKIE)
    r = client.post("/billing/webhooks/mock", json={"event": "ping"})
    assert r.status_code != 403  # вебхуки освобождены (проверяются подписью)
