"""Тесты UI дашборда и платформенных workspace-страниц (offline, TestClient)."""

from fastapi.testclient import TestClient

from app.config import get_settings

DASH = "/ui/projects/1/dashboard"


def test_dashboard_has_platform_grid_and_icons(client: TestClient) -> None:
    body = client.get(DASH).text
    assert "platform-grid" in body
    assert "platform-icon" in body
    assert "<svg" in body  # оригинальные inline-иконки


def test_dashboard_shows_core_and_planned_platforms(client: TestClient) -> None:
    body = client.get(DASH).text
    for title in ("Telegram", "ВКонтакте", "Instagram"):
        assert title in body, title
    # Планируемые площадки тоже видны (кликабельные карточки «в планах»).
    for title in ("TikTok", "TenChat", "Авито"):
        assert title in body, title


def test_telegram_workspace_has_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "BotFather" in body
    assert "chat not found" in body or "getChat" in body


def test_vk_workspace_has_user_token_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/vk").text
    assert "27" in body  # ошибка 27
    assert "user-token" in body
    assert "HTTPS" in body


def test_instagram_workspace_has_image_url_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/instagram").text
    assert "image_url" in body
    assert "Meta Developer" in body or "Graph API" in body


def test_planned_workspace_shows_in_development(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/tiktok").text
    assert "интеграция в разработке" in body.lower()
    assert "Роадмап" in body


def test_workspace_no_raw_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.vk_app_secret,
        settings.instagram_app_secret,
        settings.instagram_access_token,
        settings.vk_access_token,
        settings.telegram_bot_token,
    ]
    for platform in ("telegram", "vk", "instagram", "tiktok"):
        body = client.get(f"/ui/projects/1/platforms/{platform}").text
        for secret in secrets:
            if secret:
                assert secret not in body


def test_dashboard_and_workspace_no_publish_due(client: TestClient) -> None:
    for url in (DASH, "/ui/projects/1/platforms/telegram"):
        body = client.get(url).text.lower()
        assert "publish-due" not in body
        assert "publish_due" not in body
