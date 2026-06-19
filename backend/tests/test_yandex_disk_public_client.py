"""Тесты публичного клиента Яндекс Диска (httpx.MockTransport, без сети, без токена)."""

import httpx
import pytest

from app.integrations.yandex_disk.client import (
    YandexDiskNotFoundError,
    YandexDiskPublicClient,
)

BASE = "https://disk.example/v1/disk"
_AUTH_SEEN = {"present": False}


def _handler(request: httpx.Request) -> httpx.Response:
    if any(key.lower() == "authorization" for key in request.headers):
        _AUTH_SEEN["present"] = True
    if request.url.path.endswith("/public/resources/download"):
        return httpx.Response(200, json={"href": "https://dl.example/file"})
    path = request.url.params.get("path")
    if path == "/missing":
        return httpx.Response(404, json={"message": "not found"})
    if path in (None, "/SMM"):
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {"name": "Тион", "path": "/SMM/Тион", "type": "dir"},
                        {
                            "name": "a.jpg",
                            "path": "/SMM/a.jpg",
                            "type": "file",
                            "media_type": "image",
                            "mime_type": "image/jpeg",
                        },
                    ]
                }
            },
        )
    if path == "/SMM/Тион":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {
                            "name": "b.png",
                            "path": "/SMM/Тион/b.png",
                            "type": "file",
                            "media_type": "image",
                        },
                        {
                            "name": "c.mp4",
                            "path": "/SMM/Тион/c.mp4",
                            "type": "file",
                            "media_type": "video",
                        },
                    ]
                }
            },
        )
    return httpx.Response(200, json={"_embedded": {"items": []}})


def _client() -> YandexDiskPublicClient:
    return YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(_handler))


def test_list_public_resources_parses_embedded_items() -> None:
    resources = _client().list_public_resources("https://disk.yandex.ru/d/X", "/SMM")
    assert {r.name for r in resources} == {"Тион", "a.jpg"}
    image = next(r for r in resources if r.name == "a.jpg")
    assert image.is_file
    assert image.is_media


def test_recursive_returns_only_files() -> None:
    files = _client().list_public_files_recursive("pk", "/SMM", max_depth=5)
    assert sorted(f.name for f in files) == ["a.jpg", "b.png", "c.mp4"]
    assert all(f.is_file for f in files)


def test_download_url_parses_href() -> None:
    assert _client().get_public_download_url("pk", "/SMM/a.jpg") == "https://dl.example/file"


def test_not_found_raises() -> None:
    with pytest.raises(YandexDiskNotFoundError):
        _client().list_public_resources("pk", "/missing")


def test_no_oauth_token_required() -> None:
    _AUTH_SEEN["present"] = False
    _client().list_public_resources("pk", "/SMM")
    assert _AUTH_SEEN["present"] is False
