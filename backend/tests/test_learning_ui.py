"""Тесты UI блока «Чему бот научился» (v0.4.0, offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_learning_index_renders(client: TestClient) -> None:
    body = client.get("/ui/learning").text
    assert "Чему бот научился" in body


def test_project_learning_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/learning").text
    assert "Чему бот научился" in body


def test_learning_shows_sections(client: TestClient) -> None:
    body = client.get("/ui/projects/1/learning").text
    for heading in (
        "Предпочитаемые темы",
        "Отклонённые темы",
        "Лучший призыв к действию",
        "Сильные теги",
        "Слабые теги",
        "Уверенность профиля",
    ):
        assert heading in body


def test_learning_no_publish_due(client: TestClient) -> None:
    for url in ("/ui/learning", "/ui/projects/1/learning"):
        low = client.get(url).text.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low


def test_learning_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/projects/1/learning").text
    for secret in secrets:
        if secret:
            assert secret not in body
