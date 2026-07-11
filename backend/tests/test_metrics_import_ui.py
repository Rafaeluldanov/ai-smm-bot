"""Тесты UI метрик и обучения (v0.4.1, offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_metrics_index_renders(client: TestClient) -> None:
    body = client.get("/ui/metrics").text
    assert "Метрики и обучение" in body


def test_project_metrics_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics").text
    assert "Метрики и обучение" in body


def test_metrics_has_source_filters(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics").text
    for source in ("demo", "manual", "estimated", "internal", "api"):
        assert source in body


def test_metrics_has_action_buttons(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics").text
    for label in (
        "Preview import",
        "Run demo import",
        "Внести метрики вручную",
        "Пересчитать обучение",
    ):
        assert label in body


def test_metrics_has_manual_form(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics").text
    assert "publication_id" in body
    assert "followers_delta" in body


def test_metrics_has_disabled_warning(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics").text
    assert "Реальные API-метрики выключены" in body
    assert "не являются реальными" in body


def test_learning_metrics_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/learning/metrics").text
    assert "Как метрики повлияли на обучение" in body


def test_metrics_import_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics/import").text
    assert "Импорт метрик" in body


def test_metrics_manual_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/metrics/manual").text
    assert "Ручной ввод метрик" in body


def test_metrics_no_publish_due(client: TestClient) -> None:
    for url in (
        "/ui/metrics",
        "/ui/projects/1/metrics",
        "/ui/projects/1/metrics/import",
        "/ui/projects/1/metrics/manual",
        "/ui/projects/1/learning/metrics",
    ):
        low = client.get(url).text.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low
        assert "опубликовать live" not in low


def test_metrics_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/projects/1/metrics").text
    for secret in secrets:
        if secret:
            assert secret not in body


def test_metrics_sidebar_link(client: TestClient) -> None:
    assert "/ui/metrics" in client.get("/ui/projects").text
