"""Тесты UI Autonomous Business OS (v0.7.0): страница «AI директор бизнеса»."""

from fastapi.testclient import TestClient


def test_executive_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/executive")
    assert r.status_code == 200
    html = r.text
    assert "AI директор бизнеса" in html
    assert "Health бизнеса" in html
    assert "Приоритеты" in html
    assert "Бизнес-действия" in html
    assert "Цель бизнеса" in html


def test_executive_page_has_review_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/executive").text
    for label in ("Принять", "Отклонить", "Применить"):
        assert label in html


def test_executive_page_calls_executive_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/executive").text
    assert "/executive/analyze" in html
    assert "/actions/" in html
    assert "APPLY_BUSINESS_ACTION" in html
    # advisory-экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
