"""Тесты UI режима автоматизации (v0.4.0, offline)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_project_automation_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "Режим автоматизации" in body


def test_automation_shows_mode_toggles(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "semi_auto" in body
    assert "full_auto" in body
    assert "Полуавтоматический" in body
    assert "Полностью автоматический" in body


def test_automation_shows_confirmation_phrase(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "ENABLE_FULL_AUTO" in body


def test_automation_shows_safety_gates(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "safety gates" in body
    for gate in (
        "Баланс units достаточен",
        "Платформа подключена",
        "Живая публикация включена",
        "Качество контента выше порога",
    ):
        assert gate in body


def test_automation_warns_live_gated(client: TestClient) -> None:
    body = client.get("/ui/projects/1/automation").text
    assert "публикует live только если включены все safety gates" in body


def test_automation_no_publish_due(client: TestClient) -> None:
    low = client.get("/ui/projects/1/automation").text.lower()
    assert "publish-due" not in low
    assert "publish_due" not in low
    assert "опубликовать live" not in low


def test_automation_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [settings.telegram_bot_token, settings.vk_access_token]
    body = client.get("/ui/projects/1/automation").text
    for secret in secrets:
        if secret:
            assert secret not in body
