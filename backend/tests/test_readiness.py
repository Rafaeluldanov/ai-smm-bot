"""Тесты readiness endpoint."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_readiness_returns_safe_summary() -> None:
    response = client.get("/health/readiness")

    assert response.status_code == 200

    body = response.json()
    assert body["status"] in {"ready", "degraded"}
    assert "app_env" in body
    assert "database" in body
    assert "integrations" in body
    assert "warnings" in body

    assert isinstance(body["integrations"]["telegram"], bool)
    assert isinstance(body["integrations"]["vk"], bool)
    assert isinstance(body["integrations"]["yandex_disk"], bool)
    assert isinstance(body["integrations"]["ai"], bool)


def test_readiness_does_not_expose_secret_values() -> None:
    body = client.get("/health/readiness").json()
    serialized = str(body)

    forbidden_fragments = [
        "TELEGRAM_BOT_TOKEN",
        "VK_ACCESS_TOKEN",
        "YANDEX_DISK_TOKEN",
        "AI_API_KEY",
        "telegram_bot_token",
        "vk_access_token",
        "yandex_disk_token",
        "ai_api_key",
    ]

    for fragment in forbidden_fragments:
        assert fragment not in serialized
