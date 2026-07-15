"""Тесты UI AI Decision Engine (v0.7.4): страница «AI решения»."""

from fastapi.testclient import TestClient


def test_decisions_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/decisions")
    assert r.status_code == 200
    html = r.text
    assert "AI решения" in html
    assert "Проблема" in html
    assert "Варианты" in html
    assert "Рекомендация AI" in html


def test_decisions_page_has_action_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/decisions").text
    for label in ("Создать", "Проанализировать", "Выбрать", "Применить"):
        assert label in html


def test_decisions_page_calls_decision_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/decisions").text
    assert "/ai-decisions" in html
    assert "/analyze" in html
    assert "/scenarios/" in html
    assert "APPLY_DECISION" in html
    # аналитический экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
