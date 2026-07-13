"""Тесты UI Telegram-уведомлений (v0.5.4). Страницы рендерятся; без bot token; баннер на месте."""

from fastapi.testclient import TestClient


def test_telegram_page_renders(client: TestClient) -> None:
    r = client.get("/ui/notification-telegram")
    assert r.status_code == 200
    html = r.text
    assert "Telegram-уведомления" in html
    assert "Реальная Telegram-доставка выключена" in html


def test_project_telegram_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/notification-telegram")
    assert r.status_code == 200
    assert "Telegram-уведомления" in r.text


def test_telegram_page_has_setup_and_no_bot_token(client: TestClient) -> None:
    html = client.get("/ui/notification-telegram").text
    # Инструкция подключения присутствует.
    assert "/start" in html
    assert "Создать токен привязки" in html
    # Никакого bot token / publish-due.
    for token in ("NOTIFICATION_TELEGRAM_BOT_TOKEN", "bot_token", "publish-due", "publish_due"):
        assert token not in html


def test_delivery_page_links_telegram(client: TestClient) -> None:
    html = client.get("/ui/notification-delivery").text
    assert "/ui/notification-telegram" in html


def test_settings_page_has_telegram_block(client: TestClient) -> None:
    html = client.get("/ui/settings").text
    assert "Telegram-уведомления" in html
    assert "/ui/notification-telegram" in html
    assert "NOTIFICATION_TELEGRAM_BOT_TOKEN" not in html and "bot_token" not in html
