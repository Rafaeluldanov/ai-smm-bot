"""Тесты UI AI Workflow Manager (v0.7.2): страница «AI процессы»."""

from fastapi.testclient import TestClient


def test_workflows_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/workflows")
    assert r.status_code == 200
    html = r.text
    assert "AI процессы" in html
    assert "Активные процессы" in html
    assert "Этапы" in html
    assert "Блокеры" in html
    assert "Health Score" in html


def test_workflows_page_has_action_buttons(client: TestClient) -> None:
    html = client.get("/ui/projects/1/workflows").text
    for label in ("Создать", "Сгенерировать этапы", "Завершить", "Снять"):
        assert label in html


def test_workflows_page_calls_workflow_api(client: TestClient) -> None:
    html = client.get("/ui/projects/1/workflows").text
    assert "/generate-steps" in html
    assert "/steps/" in html
    assert "/blockers" in html
    assert "/health" in html
    # workflow-management экран не публикует и не включает live.
    assert "publish_once_if_allowed" not in html
    assert "live_publishing" not in html
