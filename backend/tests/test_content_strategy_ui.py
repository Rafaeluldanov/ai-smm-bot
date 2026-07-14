"""Тесты UI автономного контент-стратега (v0.6.6): страница «AI стратегия контента»."""

from fastapi.testclient import TestClient


def test_strategy_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/strategy")
    assert r.status_code == 200
    html = r.text
    assert "AI стратегия контента" in html
    assert "Что AI понял" in html
    assert "План месяца" in html
    assert "Рекомендации" in html


def test_strategy_page_has_review_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/strategy").text
    for label in ("Принять", "Отклонить", "Применить"):
        assert label in html


def test_strategy_page_calls_strategy_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/strategy").text
    assert "/strategy/analyze" in html
    assert "/strategy/apply" in html
    # apply отправляет обязательное подтверждение.
    assert "APPLY_STRATEGY" in html
    # экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
