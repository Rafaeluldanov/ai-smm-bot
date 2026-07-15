"""Тесты UI AI Operations Control Center (v0.7.3): страница «AI Operations Center»."""

from fastapi.testclient import TestClient


def test_operations_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/operations")
    assert r.status_code == 200
    html = r.text
    assert "AI Operations Center" in html
    assert "Health Score" in html
    assert "Бизнес-состояние" in html
    assert "Риски" in html
    assert "AI рекомендации" in html


def test_operations_page_has_action_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/operations").text
    for label in ("Проанализировать", "Снять", "Принять", "Отклонить"):
        assert label in html


def test_operations_page_calls_operations_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/operations").text
    assert "/operations/analyze" in html
    assert "/risks/" in html
    assert "/recommendations/" in html
    # аналитический экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
