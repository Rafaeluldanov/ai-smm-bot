"""Тесты probe-CLI (offline; httpx.MockTransport; без wall.post и без токена в выводе)."""

from pathlib import Path

import httpx
import pytest

from app.integrations.vk.client import VKPublishingClient
from app.scripts import vk_api_photo_probe as probe

TOKEN = "SECRET_VK_TOKEN_do_not_leak"
ALBUM_TITLE = "AI SMM Bot uploads"


def _transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "groups.getById" in path:
            return httpx.Response(200, json={"response": [{"id": 100, "name": "TEEON"}]})
        if "photos.getWallUploadServer" in path:
            return httpx.Response(200, json={"error": {"error_code": 27, "error_msg": "group"}})
        if "photos.getAlbums" in path:
            return httpx.Response(
                200, json={"response": {"items": [{"id": 555, "title": ALBUM_TITLE}]}}
            )
        return httpx.Response(200, json={"error": {"error_code": 100, "error_msg": "x"}})

    return httpx.MockTransport(handler)


def _client() -> VKPublishingClient:
    return VKPublishingClient(
        token=TOKEN,
        default_target_id="-240102732",
        transport=_transport(),
        photo_upload_strategy="auto",
        photo_album_title=ALBUM_TITLE,
    )


def test_prepare_probe_image_uses_given_path(tmp_path: Path) -> None:
    img = tmp_path / "my.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0custom")
    assert probe.prepare_probe_image(str(img)) == b"\xff\xd8\xff\xe0custom"


def test_prepare_probe_image_default_is_valid_jpeg() -> None:
    data = probe.prepare_probe_image(None)
    assert data[:2] == b"\xff\xd8"  # JPEG SOI marker


def test_run_readonly_recommends_album_without_token_leak(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = probe.run(
        _client(),
        allow_upload=False,
        group_id=None,
        album_id=None,
        album_title=None,
        image_bytes=None,
    )
    assert result["recommended_strategy"] == "album"
    out = capsys.readouterr().out
    assert "RECOMMENDED_STRATEGY=album" in out
    assert "WALL:" in out and "ALBUM:" in out
    assert TOKEN not in out
