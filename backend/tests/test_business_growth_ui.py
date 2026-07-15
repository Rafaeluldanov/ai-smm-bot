"""Тесты UI AI Business Growth Agent (v0.6.9): страница «AI рост бизнеса»."""

from fastapi.testclient import TestClient


def test_growth_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/growth")
    assert r.status_code == 200
    html = r.text
    assert "AI рост бизнеса" in html
    assert "Growth Score" in html
    assert "Что работает" in html
    assert "Где рост" in html
    assert "Рекомендации AI" in html


def test_growth_page_has_review_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/growth").text
    for label in ("Принять", "Отклонить", "Применить"):
        assert label in html


def test_growth_page_calls_growth_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/growth").text
    assert "/growth/analyze" in html
    assert "/growth/apply" in html
    assert "APPLY_GROWTH_ACTION" in html
    # advisory-экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
