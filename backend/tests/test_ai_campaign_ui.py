"""Тесты UI AI Campaign Manager (v0.6.7): страница «AI кампании»."""

from fastapi.testclient import TestClient


def test_campaigns_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/campaigns")
    assert r.status_code == 200
    html = r.text
    assert "AI кампании" in html
    assert "Создать кампанию" in html
    assert "План кампании" in html
    assert "Почему AI выбрал" in html
    assert "Рекомендации" in html


def test_campaigns_page_has_review_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/campaigns").text
    for label in ("Принять", "Отклонить", "Одобрить кампанию", "Применить"):
        assert label in html


def test_campaigns_page_calls_campaign_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/campaigns").text
    assert "/campaigns/" in html
    assert "APPLY_CAMPAIGN" in html
    # экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
