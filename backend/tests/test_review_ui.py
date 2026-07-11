"""Тесты UI очереди ревью (v0.4.0, offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_review_index_renders(client: TestClient) -> None:
    body = client.get("/ui/review").text
    assert "Очередь на ревью" in body
    assert "Полуавтоматический" in body


def test_project_review_renders_with_buttons(client: TestClient) -> None:
    body = client.get("/ui/projects/1/review").text
    assert "Очередь постов на ревью" in body
    for label in ("Открыть", "Одобрить", "Запросить правки", "Отклонить", "Опубликовать"):
        assert label in body


def test_review_shows_publish_disabled_message(client: TestClient) -> None:
    body = client.get("/ui/projects/1/review").text
    assert "Живая публикация выключена" in body


def test_review_sidebar_links_present(client: TestClient) -> None:
    body = client.get("/ui/projects/1/review").text
    assert "/ui/review" in body
    assert "/ui/learning" in body


def test_review_no_publish_due(client: TestClient) -> None:
    for url in ("/ui/review", "/ui/projects/1/review"):
        low = client.get(url).text.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low
        assert "опубликовать live" not in low


def test_review_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/projects/1/review").text
    for secret in secrets:
        if secret:
            assert secret not in body
