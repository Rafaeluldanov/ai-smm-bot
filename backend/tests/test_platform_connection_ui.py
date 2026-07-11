"""Тесты UI формы подключения платформы в workspace (offline, TestClient)."""

from fastapi.testclient import TestClient

from app.config import get_settings


def _ws(client: TestClient, platform: str) -> str:
    return client.get(f"/ui/projects/1/platforms/{platform}").text


def test_workspace_has_connection_form(client: TestClient) -> None:
    body = _ws(client, "telegram")
    assert "conn-card" in body
    assert "Подключение" in body
    assert "connSave" in body and "connCheck" in body


def test_telegram_has_botfather_help(client: TestClient) -> None:
    body = _ws(client, "telegram")
    assert "BotFather" in body
    assert "Bot token" in body


def test_vk_has_access_token_and_group_id(client: TestClient) -> None:
    body = _ws(client, "vk")
    assert "Access token" in body
    assert "Group ID" in body


def test_instagram_has_image_url_warning(client: TestClient) -> None:
    body = _ws(client, "instagram")
    assert "image_url" in body


def test_secret_placeholder_text_present(client: TestClient) -> None:
    body = _ws(client, "telegram")
    assert "пустым, чтобы не менять" in body


def test_last_check_and_status_block(client: TestClient) -> None:
    body = _ws(client, "telegram")
    assert "conn-status" in body
    assert "Проверить подключение" in body


def test_audit_log_block_present(client: TestClient) -> None:
    body = _ws(client, "telegram")
    assert "conn-logs" in body
    assert "Журнал действий" in body


def test_no_raw_secret_in_html(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.telegram_bot_token,
        settings.vk_access_token,
        settings.vk_app_secret,
        settings.instagram_access_token,
        settings.instagram_app_secret,
    ]
    for platform in ("telegram", "vk", "instagram", "yandex_disk"):
        body = _ws(client, platform)
        for secret in secrets:
            if secret:
                assert secret not in body


def test_no_publish_due_in_html(client: TestClient) -> None:
    body = _ws(client, "telegram").lower()
    assert "publish-due" not in body
    assert "publish_due" not in body


def test_planned_workspace_form_disabled(client: TestClient) -> None:
    body = _ws(client, "tiktok")
    assert "Интеграция в разработке" in body
    assert "интеграция в разработке" in body.lower()
