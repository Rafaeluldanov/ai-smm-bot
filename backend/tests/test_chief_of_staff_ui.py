"""Тесты UI AI Chief of Staff (v0.7.1): страница «AI помощник руководителя»."""

from fastapi.testclient import TestClient


def test_chief_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/chief-of-staff")
    assert r.status_code == 200
    html = r.text
    assert "AI помощник руководителя" in html
    assert "главные изменения" in html
    assert "Риски" in html
    assert "Возможности" in html
    assert "Задачи AI" in html
    assert "Память решений" in html


def test_chief_page_has_task_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/chief-of-staff").text
    for label in ("Принять", "Отклонить", "Завершить"):
        assert label in html


def test_chief_page_calls_chief_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/chief-of-staff").text
    assert "/briefing/generate" in html
    assert "/briefing/weekly" in html
    assert "/tasks/" in html
    assert "/decisions" in html
    # advisory-экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
