"""Тесты UI движка автоматизации расписаний (offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_workspace_has_schedule_automation_block(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "Автоматизация расписаний" in body
    assert "sched-automation" in body


def test_workspace_has_automation_buttons(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "Preview due" in body
    assert "Создать drafts сейчас" in body
    assert "История запусков" in body


def test_workspace_shows_connection_and_live_warnings(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "Подключите платформу" in body
    assert "Живая публикация выключена" in body


def test_schedule_runs_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/schedule-runs").text
    assert "История запусков расписания" in body
    assert "sr-list" in body
    assert "draft_created" in body


def test_no_live_publish_button(client: TestClient) -> None:
    for url in ("/ui/projects/1/platforms/telegram", "/ui/projects/1/schedule-runs"):
        low = client.get(url).text.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low
        assert "опубликовать live" not in low


def test_no_raw_secrets_in_ui(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.telegram_bot_token,
        settings.vk_access_token,
        settings.instagram_access_token,
    ]
    for url in ("/ui/projects/1/platforms/telegram", "/ui/projects/1/schedule-runs"):
        body = client.get(url).text
        for secret in secrets:
            if secret:
                assert secret not in body
