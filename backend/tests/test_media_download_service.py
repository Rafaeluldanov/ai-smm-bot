"""Тесты сервиса загрузки медиа (fake-клиент + MockTransport, без сети)."""

import httpx
import pytest

from app.models.media_asset import MediaAsset
from app.services.media_download_service import (
    MediaDownloadNotConfiguredError,
    MediaDownloadService,
    MediaSourceNotSupportedError,
)


class _FakePublicClient:
    def __init__(self, href: str = "https://downloader.disk.yandex.ru/file.jpg") -> None:
        self.href = href
        self.calls: list[tuple[str, str | None]] = []

    def get_public_download_url(self, public_key: str, path: str | None = None) -> str:
        self.calls.append((public_key, path))
        return self.href


def _asset(path: str, file_name: str = "a.jpg") -> MediaAsset:
    return MediaAsset(id=1, project_id=1, file_name=file_name, yandex_disk_path=path)


def test_public_download_via_mock_transport() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"IMGDATA")

    client = _FakePublicClient()
    service = MediaDownloadService(
        public_client=client,
        public_key="https://disk.yandex.ru/d/X",
        transport=httpx.MockTransport(handler),
    )
    result = service.download_media_asset(None, _asset("public://yandex/teeon/SMM/Тион/a.jpg"))

    assert result.bytes == b"IMGDATA"
    assert result.content_type == "image/jpeg"
    assert result.source_url == client.href
    # Путь для публичного клиента построен без slug проекта.
    assert client.calls[0][1] == "/SMM/Тион/a.jpg"


def test_external_source_unsupported() -> None:
    service = MediaDownloadService(public_client=_FakePublicClient(), public_key="X")
    with pytest.raises(MediaSourceNotSupportedError):
        service.download_media_asset(None, _asset("external://unsplash/123"))


def test_private_path_unsupported() -> None:
    service = MediaDownloadService(public_client=_FakePublicClient(), public_key="X")
    with pytest.raises(MediaSourceNotSupportedError):
        service.download_media_asset(None, _asset("/SMM_BOT/01_TEEON/a.jpg"))


def test_public_without_key_not_configured() -> None:
    service = MediaDownloadService(public_client=_FakePublicClient(), public_key=None)
    with pytest.raises(MediaDownloadNotConfiguredError):
        service.download_media_asset(None, _asset("public://yandex/teeon/SMM/Тион/a.jpg"))
