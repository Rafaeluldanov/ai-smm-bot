"""Тесты UI авто-синхронизации Яндекс Диска (v0.5.7). Рендер; без секретов/publish-due."""

from fastapi.testclient import TestClient


def test_yandex_sync_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/yandex-sync")
    assert r.status_code == 200
    assert "Картинки из Яндекс Диска" in r.text
    assert "Файлы не удаляются" in r.text
    assert "Синхронизировать сейчас" in r.text


def test_autopilot_media_page_shows_sync(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/media").text
    assert "/ui/projects/1/yandex-sync" in html
    assert "Синхронизировать сейчас" in html


def test_page_no_publish_due_no_secrets(client: TestClient) -> None:
    for p in ("/ui/projects/1/yandex-sync", "/ui/projects/1/autopilot/media"):
        html = client.get(p).text
        assert "publish-due" not in html
        assert "publish_due" not in html
        assert "YANDEX_DISK_TOKEN" not in html
        assert "api_key_encrypted" not in html


def test_page_no_internal_paths(client: TestClient) -> None:
    html = client.get("/ui/projects/1/yandex-sync").text
    # Нет абсолютных внутренних путей в разметке.
    assert "/Users/" not in html
    assert "/var/" not in html


def test_advanced_links_sync(client: TestClient) -> None:
    html = client.get("/ui/advanced").text
    assert "Синхронизация медиа" in html
