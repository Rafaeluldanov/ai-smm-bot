"""Тесты in-memory rate limiting (fixed-window)."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.rate_limit import rate_limiter

_RL_ON = Settings(_env_file=None, rate_limit_enabled=True, rate_limit_auth_per_minute=3)


@pytest.fixture(autouse=True)
def _reset_limiter():  # noqa: ANN201
    rate_limiter.reset()
    yield
    rate_limiter.reset()


def _login(client: TestClient, ip: str) -> int:
    return client.post(
        "/auth/login",
        json={"email": "x@e.com", "password": "nope12345"},
        headers={"X-Forwarded-For": ip},
    ).status_code


def test_disabled_no_limit(client: TestClient) -> None:
    # По умолчанию rate limiting выключен — 429 не появляется.
    codes = [_login(client, "9.9.9.9") for _ in range(10)]
    assert 429 not in codes


def test_enabled_returns_429_after_limit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.security_middleware.get_settings", lambda: _RL_ON)
    codes = [_login(client, "1.1.1.1") for _ in range(4)]
    assert codes[:3].count(429) == 0  # первые 3 в пределах лимита
    assert codes[3] == 429  # 4-й превышает лимит=3


def test_separate_keys_independent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.security_middleware.get_settings", lambda: _RL_ON)
    for _ in range(4):
        _login(client, "1.1.1.1")  # исчерпать лимит для первого IP
    # Другой IP — свой bucket, первый запрос проходит.
    assert _login(client, "2.2.2.2") != 429


def test_retry_after_header_present(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.security_middleware.get_settings", lambda: _RL_ON)
    resp = None
    for _ in range(5):
        resp = client.post(
            "/auth/login",
            json={"email": "x@e.com", "password": "nope12345"},
            headers={"X-Forwarded-For": "3.3.3.3"},
        )
        if resp.status_code == 429:
            break
    assert resp is not None and resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}
