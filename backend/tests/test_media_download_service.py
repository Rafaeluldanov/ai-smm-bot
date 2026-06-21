"""Тесты сервиса загрузки медиа (fake-клиент + MockTransport, без сети)."""

import httpx
import pytest

from app.integrations.yandex_disk.client import YandexDiskPublicClient
from app.models.media_asset import MediaAsset
from app.services.media_download_service import (
    MediaDownloadError,
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


# --- Сквозной кейс с реальным публичным клиентом (download 404 -> метаданные) ---


def _yandex_handler(request: httpx.Request) -> httpx.Response:
    # На реальном публичном диске download-эндпоинт 404-ит для HEIC.
    if request.url.path.endswith("/public/resources/download"):
        return httpx.Response(404, json={"message": "not found"})
    if request.url.path.endswith("/public/resources"):
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {
                            "name": "IMG_5007.HEIC",
                            "path": "/teeon/IMG_5007.HEIC",
                            "type": "file",
                            "media_type": "image",
                            "file": "https://dl.example/heic-direct",
                        }
                    ]
                }
            },
        )
    if "heic-direct" in str(request.url):
        return httpx.Response(200, content=b"HEICBYTES")
    return httpx.Response(404, json={"message": "unexpected"})


def test_public_download_uses_metadata_file_when_endpoint_404s() -> None:
    transport = httpx.MockTransport(_yandex_handler)
    public_client = YandexDiskPublicClient(
        base_url="https://disk.example/v1/disk", transport=transport
    )
    service = MediaDownloadService(
        public_client=public_client,
        public_key="https://disk.yandex.ru/d/X",
        transport=transport,
    )
    result = service.download_media_asset(
        None, _asset("public://yandex/teeon/teeon/IMG_5007.HEIC", file_name="IMG_5007.HEIC")
    )
    assert result.bytes == b"HEICBYTES"
    assert result.content_type == "image/heic"


def test_public_download_clear_error_when_no_href_and_no_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"_embedded": {"items": []}})

    transport = httpx.MockTransport(handler)
    public_client = YandexDiskPublicClient(
        base_url="https://disk.example/v1/disk", transport=transport
    )
    service = MediaDownloadService(
        public_client=public_client,
        public_key="https://disk.yandex.ru/d/X",
        transport=transport,
    )
    with pytest.raises(MediaDownloadError) as excinfo:
        service.download_media_asset(
            None, _asset("public://yandex/teeon/teeon/IMG_5007.HEIC", file_name="IMG_5007.HEIC")
        )
    assert "Не удалось получить ссылку на скачивание" in str(excinfo.value)
