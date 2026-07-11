"""Тесты API фонового scheduler-worker (offline, безопасно)."""

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def test_status_endpoint(client: TestClient) -> None:
    r = client.get("/scheduler-worker/status")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["live_publish"] is False
    assert body["warnings"]


def test_leases_endpoint(client: TestClient) -> None:
    assert client.get("/scheduler-worker/leases").status_code == 200


def test_tick_dry_no_writes(client: TestClient, db_session) -> None:  # noqa: ANN001
    from app.models.post import Post

    r = client.post("/scheduler-worker/tick-dry", json={})
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert r.json()["drafts_created"] == 0
    # Dry-run не создаёт постов (общая тестовая БД).
    assert db_session.query(Post).count() == 0


def test_tick_disabled_requires_force(client: TestClient) -> None:
    r = client.post("/scheduler-worker/tick", json={})
    assert r.status_code == 400
    r2 = client.post("/scheduler-worker/tick", json={"force": True})
    assert r2.status_code == 200


def test_tick_requires_superuser_in_production(client: TestClient) -> None:
    prod = Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="prod-strong-secret-value-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )
    app.dependency_overrides[get_settings] = lambda: prod
    try:
        # Анонимный запрос в production → 401 (нужна авторизация суперпользователя).
        assert client.post("/scheduler-worker/tick-dry", json={}).status_code == 401
    finally:
        app.dependency_overrides.pop(get_settings, None)


def test_no_publish_due_or_secrets(client: TestClient) -> None:
    status_text = client.get("/scheduler-worker/status").text
    tick_text = client.post("/scheduler-worker/tick-dry", json={}).text
    for text in (status_text, tick_text):
        assert "publish-due" not in text.lower()
        assert "publish_due" not in text.lower()
