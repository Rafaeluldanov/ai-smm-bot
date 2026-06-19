"""Сервис получения байтов медиа-актива для последующей обработки.

Назначение — отдать СОДЕРЖИМОЕ изображения по ``MediaAsset`` (только для
производной обработки/улучшения). Источники:

- ``public://yandex/<slug>/<path>`` — публичная папка Яндекс Диска: получаем
  download-href через публичный клиент (без токена) и скачиваем байты;
- ``external://...`` — внешние стоки: на этом этапе НЕ скачиваем (unsupported);
- приватный путь (``disk:/`` или ``/SMM_BOT/...``) — пока не поддержан здесь.

В тестах сеть не вызывается: публичный клиент и HTTP-транспорт подменяются
(``httpx.MockTransport`` / fake-клиент).
"""

from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.integrations.yandex_disk.client import YandexDiskError
from app.models.media_asset import MediaAsset

logger = get_logger(__name__)

_PUBLIC_PREFIX = "public://yandex/"
_EXTERNAL_PREFIX = "external://"

# Расширение -> MIME (для content_type загруженного файла).
_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


class MediaDownloadError(Exception):
    """Базовая ошибка загрузки медиа."""


class MediaSourceNotSupportedError(MediaDownloadError):
    """Источник медиа не поддерживается для скачивания на этом этапе."""


class MediaDownloadNotConfiguredError(MediaDownloadError):
    """Загрузчик не настроен (например, нет публичной ссылки Яндекс Диска)."""


@dataclass(slots=True)
class DownloadedMedia:
    """Скачанное содержимое медиа-актива (в памяти)."""

    file_name: str
    content_type: str
    bytes: bytes
    source_url: str
    warnings: list[str] = field(default_factory=list)


class SupportsPublicDownloadUrl(Protocol):
    """Минимальный контракт публичного клиента Яндекс Диска."""

    def get_public_download_url(self, public_key: str, path: str | None = None) -> str: ...


class SupportsMediaDownload(Protocol):
    """Контракт загрузчика медиа (для подмены в тестах и DI)."""

    def download_media_asset(self, db: Session, media_asset: MediaAsset) -> "DownloadedMedia": ...


class MediaDownloadService:
    """Отдаёт байты медиа-актива из поддерживаемых источников."""

    def __init__(
        self,
        public_client: SupportsPublicDownloadUrl,
        public_key: str | None,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._public_client = public_client
        self._public_key = public_key
        self._timeout = timeout
        self._transport = transport

    def download_media_asset(self, db: Session, media_asset: MediaAsset) -> DownloadedMedia:
        """Скачать байты медиа-актива. Бросает понятную ошибку для неподдержанных источников."""
        path = media_asset.yandex_disk_path or ""
        if path.startswith(_PUBLIC_PREFIX):
            return self._download_public(media_asset, path)
        if path.startswith(_EXTERNAL_PREFIX):
            raise MediaSourceNotSupportedError(
                "Внешние изображения (external://) не скачиваются на этом этапе"
            )
        raise MediaSourceNotSupportedError(
            f"Источник медиа не поддержан загрузчиком: {path or '<пусто>'}"
        )

    # --- Внутреннее ---

    def _download_public(self, media_asset: MediaAsset, disk_path: str) -> DownloadedMedia:
        if not self._public_key:
            raise MediaDownloadNotConfiguredError(
                "Публичная ссылка Яндекс Диска не настроена (YANDEX_DISK_PUBLIC_SMM_URL)"
            )
        public_path = self._public_path_from_disk_path(disk_path)
        try:
            href = self._public_client.get_public_download_url(self._public_key, public_path)
        except YandexDiskError as exc:
            raise MediaDownloadError(f"Не удалось получить ссылку на скачивание: {exc}") from exc

        content = self._http_get_bytes(href)
        return DownloadedMedia(
            file_name=media_asset.file_name,
            content_type=self._content_type(media_asset.file_name),
            bytes=content,
            source_url=href,
        )

    @staticmethod
    def _public_path_from_disk_path(disk_path: str) -> str:
        """Из ``public://yandex/<slug>/<path>`` вернуть реальный путь ``/<path>``."""
        rest = disk_path[len(_PUBLIC_PREFIX) :]
        _slug, _, real = rest.partition("/")
        return f"/{real}" if real else "/"

    def _http_get_bytes(self, url: str) -> bytes:
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(url, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise MediaDownloadError(f"Сетевая ошибка при скачивании файла: {exc}") from exc
        if response.status_code >= 400:
            raise MediaDownloadError(f"Скачивание вернуло HTTP {response.status_code} для {url}")
        return response.content

    @staticmethod
    def _content_type(file_name: str) -> str:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        return _CONTENT_TYPES.get(ext, "application/octet-stream")
