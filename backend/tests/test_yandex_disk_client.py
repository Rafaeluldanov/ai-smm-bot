"""Тесты клиента Яндекс Диска (через httpx.MockTransport, без сети)."""

import httpx
import pytest

from app.integrations.yandex_disk.client import (
    YandexDiskAuthError,
    YandexDiskClient,
    YandexDiskNotFoundError,
)

BASE = "https://disk.example/v1/disk"


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.params.get("path")
    if request.url.path.endswith("/resources/download"):
        return httpx.Response(200, json={"href": "https://dl.example/file"})
    if path == "/missing":
        return httpx.Response(404, json={"message": "not found"})
    if path == "/root":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {
                            "name": "a.jpg",
                            "path": "disk:/root/a.jpg",
                            "type": "file",
                            "mime_type": "image/jpeg",
                            "size": 100,
                            "modified": "2024-01-01T10:00:00+00:00",
                        },
                        {"name": "sub", "path": "disk:/root/sub", "type": "dir"},
                    ]
                }
            },
        )
    if path == "disk:/root/sub":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {"name": "b.png", "path": "disk:/root/sub/b.png", "type": "file"},
                        {"name": "c.mp4", "path": "disk:/root/sub/c.mp4", "type": "file"},
                    ]
                }
            },
        )
    return httpx.Response(200, json={"_embedded": {"items": []}})


def _client(token: str | None = "test-token") -> YandexDiskClient:
    return YandexDiskClient(token=token, base_url=BASE, transport=httpx.MockTransport(_handler))


def test_list_resources_parses_embedded_items() -> None:
    resources = _client().list_resources("/root")
    assert len(resources) == 2
    assert {r.name for r in resources} == {"a.jpg", "sub"}
    a = next(r for r in resources if r.name == "a.jpg")
    assert a.is_file
    assert a.mime_type == "image/jpeg"
    assert a.size == 100
    assert a.modified is not None


def test_list_files_recursive_returns_only_files() -> None:
    files = _client().list_files_recursive("/root", max_depth=3)
    assert sorted(f.name for f in files) == ["a.jpg", "b.png", "c.mp4"]
    assert all(f.is_file for f in files)


def test_not_found_raises() -> None:
    with pytest.raises(YandexDiskNotFoundError):
        _client().list_resources("/missing")


def test_empty_token_raises_auth_error() -> None:
    with pytest.raises(YandexDiskAuthError):
        _client(token=None).list_resources("/root")


def test_get_download_url() -> None:
    assert _client().get_download_url("/root/a.jpg") == "https://dl.example/file"
