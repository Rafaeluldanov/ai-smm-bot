"""Тесты UI аналитики v0.2.13 (offline, TestClient).

Фильтры (проект/платформа/период/статус/глубина), календарь, оценка стоимости в units,
карточки постов, ручной ввод метрик, отсутствие секретов и live-вызовов внешних API.
"""

from fastapi.testclient import TestClient

ANALYTICS = "/ui/analytics"


def test_analytics_has_filters(client: TestClient) -> None:
    body = client.get(ANALYTICS).text
    for el in ("an-project", "an-platform", "an-period", "an-status", "an-depth", "an-count"):
        assert el in body, el
    # Опции периода и глубины (light/standard/deep).
    for opt in ("Сегодня", "7 дней", "30 дней", "Текущий месяц", "light", "standard", "deep"):
        assert opt in body, opt
    # Статусы календаря.
    for st in ("published", "scheduled", "failed", "needs_review"):
        assert st in body, st


def test_analytics_has_calendar_and_estimate(client: TestClient) -> None:
    body = client.get(ANALYTICS).text
    assert "an-cal" in body
    assert "Календарь" in body
    assert "an-estimate" in body
    assert "anEstimate(" in body
    assert "units" in body
    # Preview бесплатно; баланс показан.
    assert "Preview бесплатно" in body
    assert "Баланс" in body


def test_analytics_has_post_cards_and_manual_metrics(client: TestClient) -> None:
    body = client.get(ANALYTICS).text
    # Список постов + открытие анализа.
    assert "an-posts" in body
    assert "anOpenCard(" in body
    assert "Открыть анализ" in body
    # Ручной ввод метрик (бесплатно, source=manual).
    assert "Внести метрики вручную" in body
    assert "manual-metrics" in body
    for field in ("m-views", "m-reach", "m-likes", "m-clicks", "m-followers"):
        assert field in body, field


def test_analytics_detail_metrics_listed(client: TestClient) -> None:
    body = client.get(ANALYTICS).text
    for metric in ("reach", "impressions", "saves", "followers_delta", "ER", "CTR"):
        assert metric in body, metric


def test_analytics_no_secrets_no_live_calls(client: TestClient) -> None:
    body = client.get(ANALYTICS).text
    # Нет обращений к внешним соцсетям/провайдерам из разметки.
    for ext in ("graph.facebook.com", "api.vk.com", "api.telegram.org"):
        assert ext not in body, ext
    assert "publish-due" not in body
    assert "INSTAGRAM_LIVE_PUBLISHING_ENABLED=true" not in body
