"""Тесты UI Telegram webhook/polling (v0.5.5). Разделы рендерятся; без bot token; есть баннер."""

from fastapi.testclient import TestClient


def test_page_has_webhook_section(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    assert "Incoming updates / Webhook" in html
    assert "Реальные Telegram API-вызовы выключены" in html


def test_page_has_simulate_form(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    assert "Simulate /start update" in html
    assert "Проверка /start token" in html


def test_page_has_recent_updates_block(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    assert "Recent incoming updates" in html


def test_page_has_management_buttons(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    assert "Preview setWebhook" in html
    assert "getWebhookInfo dry-run" in html
    assert "polling dry-run" in html


def test_page_no_bot_token_no_publish_due(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    for token in (
        "NOTIFICATION_TELEGRAM_BOT_TOKEN",
        "bot_token",
        "NOTIFICATION_TELEGRAM_WEBHOOK_SECRET_TOKEN",
        "publish-due",
        "publish_due",
    ):
        assert token not in html


def test_project_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/notification-telegram")
    assert r.status_code == 200
    assert "Incoming updates / Webhook" in r.text


def test_settings_mentions_webhook(client: TestClient) -> None:
    html = client.get("/ui/settings").text
    assert "Webhook/polling" in html
    assert "NOTIFICATION_TELEGRAM_BOT_TOKEN" not in html
