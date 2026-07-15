"""Тесты UI AI Sales & Lead Intelligence (v0.6.8): страница «AI продажи из контента»."""

from fastapi.testclient import TestClient


def test_sales_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/sales-intelligence")
    assert r.status_code == 200
    html = r.text
    assert "AI продажи из контента" in html
    assert "Воронка" in html
    assert "Что приносит деньги" in html
    assert "Рекомендации AI" in html


def test_sales_page_calls_sales_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/sales-intelligence").text
    assert "/sales-intelligence/analyze" in html
    assert "/sales-intelligence/revenue" in html
    # аналитический экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
