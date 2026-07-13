"""Тесты UI A/B-экспериментов и оптимизации (v0.4.2, offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_experiments_index_renders(client: TestClient) -> None:
    assert "A/B-эксперименты" in client.get("/ui/experiments").text


def test_optimization_index_renders(client: TestClient) -> None:
    assert "Оптимизация тем" in client.get("/ui/optimization").text


def test_project_experiments_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiments").text
    assert "A/B" in body
    assert "Создать A/B по теме" in body


def test_project_optimization_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/optimization").text
    assert "рекомендует публиковать" in body
    assert "Рекомендации тем" in body
    assert "Публиковать чаще" in body
    assert "Избегать" in body


def test_experiment_detail_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiments/1").text
    assert "Эксперимент" in body
    assert "winner" in body or "Победитель" in body
    assert "Confidence" in body


def test_recommendations_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/recommendations").text
    assert "Рекомендации контента" in body


def test_ui_contains_ab_and_recommendations(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiments").text
    assert "A/B" in body
    body2 = client.get("/ui/projects/1/optimization").text
    assert "Рекомендации" in body2


def test_sidebar_links_present(client: TestClient) -> None:
    # v0.5.6: сложные разделы вынесены в Advanced (autopilot-first навигация).
    side = client.get("/ui/advanced").text
    assert "/ui/experiments" in side
    assert "/ui/optimization" in side


def test_dashboard_has_optimization_card(client: TestClient) -> None:
    body = client.get("/ui/projects/1/dashboard").text
    assert "Рекомендации контента" in body
    assert "A/B тесты" in body


def test_no_publish_due(client: TestClient) -> None:
    for url in (
        "/ui/experiments",
        "/ui/optimization",
        "/ui/projects/1/experiments",
        "/ui/projects/1/experiments/1",
        "/ui/projects/1/optimization",
        "/ui/projects/1/recommendations",
    ):
        low = client.get(url).text.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low
        assert "опубликовать live" not in low


def test_no_raw_tokens(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/projects/1/experiments").text
    for secret in secrets:
        if secret:
            assert secret not in body
