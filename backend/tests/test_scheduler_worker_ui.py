"""Тесты UI фонового scheduler-worker."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_scheduler_page_renders(client: TestClient) -> None:
    r = client.get("/ui/scheduler")
    assert r.status_code == 200
    body = r.text
    assert "Фоновый worker расписаний" in body
    assert "sw-status" in body


def test_scheduler_page_has_actions_and_warnings(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "Preview tick" in body
    assert "Run one safe tick" in body
    assert "Живые публикации выключены" in body
    assert "отдельным процессом" in body


def test_no_live_button_or_publish_due(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text.lower()
    assert "publish-due" not in body
    assert "publish_due" not in body
    assert "опубликовать live" not in body


def test_sidebar_has_scheduler_link(client: TestClient) -> None:
    # v0.5.6: автоматизация/планировщик доступны из Advanced (autopilot-first навигация).
    assert "/ui/scheduler" in client.get("/ui/advanced").text


def test_workspace_has_worker_mini_block(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "Фоновый worker:" in body
    assert "/ui/scheduler" in body


def test_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/scheduler").text
    for secret in secrets:
        if secret:
            assert secret not in body
