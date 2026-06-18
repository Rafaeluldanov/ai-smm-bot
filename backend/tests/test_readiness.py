"""Тесты readiness-эндпоинта (без сети и БД)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_readiness_returns_ready() -> None:
    response = client.get("/health/readiness")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["integrations"]) == {"telegram", "vk", "yandex_disk", "ai"}


def test_readiness_integrations_off_by_default() -> None:
    # Без токенов в тестовом окружении интеграции не настроены.
    body = client.get("/health/readiness").json()
    assert body["integrations"]["telegram"] is False
    assert body["integrations"]["vk"] is False
    assert body["integrations"]["ai"] is False


def test_readiness_no_production_warnings_in_local() -> None:
    body = client.get("/health/readiness").json()
    assert body["app_env"] == "local"
    assert body["warnings"] == []
