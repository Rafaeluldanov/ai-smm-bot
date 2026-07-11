"""Тесты UI аналитики /ui/analytics: календарь, фильтры, demo-метрики, источники."""

from fastapi.testclient import TestClient

from app.config import get_settings

AN = "/ui/analytics"


def test_analytics_has_calendar_and_filters(client: TestClient) -> None:
    body = client.get(AN).text
    assert "an-cal" in body  # календарь
    assert "an-project" in body  # фильтр проекта
    assert "an-platform" in body  # фильтр платформы


def test_analytics_has_scores_and_summary(client: TestClient) -> None:
    body = client.get(AN).text
    assert "quality_score" in body
    assert "engagement_score" in body
    assert "an-summary" in body  # summary cards
    assert "Demo-аналитика" in body


def test_analytics_shows_metric_sources(client: TestClient) -> None:
    body = client.get(AN).text
    for source in ("internal", "estimated", "demo"):
        assert source in body, source


def test_analytics_shows_units_cost(client: TestClient) -> None:
    body = client.get(AN).text
    assert "units" in body
    # Стоимость по глубине подгружается (light/standard/deep prices).
    assert "AN_PRICES" in body


def test_analytics_no_live_api_controls(client: TestClient) -> None:
    body = client.get(AN).text.lower()
    assert "publish-due" not in body
    assert "publish_due" not in body
    # Явно указано, что реальные вызовы внешних API не выполняются.
    assert "не выполняются" in body


def test_analytics_no_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.vk_app_secret,
        settings.instagram_app_secret,
        settings.instagram_access_token,
        settings.telegram_bot_token,
    ]
    body = client.get(AN).text
    for secret in secrets:
        if secret:
            assert secret not in body


def test_analytics_page_opens(client: TestClient) -> None:
    assert client.get(AN).status_code == 200
