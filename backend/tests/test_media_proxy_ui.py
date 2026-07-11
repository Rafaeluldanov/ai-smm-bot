"""Тесты UI media-proxy: секция в Instagram workspace + страница media-proxy."""

from fastapi.testclient import TestClient


def test_instagram_workspace_has_media_proxy_section(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/instagram").text
    assert "Публичные ссылки на медиа" in body
    assert "image_url" in body
    assert "media/public/" in body
    assert "MEDIA_PROXY_ENABLED" in body


def test_media_proxy_page_shows_status(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-proxy").text
    assert "Media Proxy" in body
    assert "mp-status" in body
    assert "Default TTL" in body
    assert "HTTPS ready" in body


def test_media_proxy_page_security_notes(client: TestClient) -> None:
    body = client.get("/ui/projects/1/media-proxy").text
    assert "sha256" in body or "хеш" in body
    assert "отзыв" in body.lower()


def test_telegram_workspace_no_media_proxy_section(client: TestClient) -> None:
    # Telegram не требует публичного image_url — секции нет.
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "mediaproxy-card" not in body


def test_no_raw_tokens_or_publish_due(client: TestClient) -> None:
    for url in ("/ui/projects/1/platforms/instagram", "/ui/projects/1/media-proxy"):
        body = client.get(url).text
        low = body.lower()
        assert "publish-due" not in low
        assert "publish_due" not in low
        # Сырых токенов /media/public/<...> в HTML быть не должно (только placeholder ****).
        assert "/media/public/ey" not in body


def test_instagram_guide_mentions_media_proxy(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/instagram").text
    assert "Media Proxy" in body
