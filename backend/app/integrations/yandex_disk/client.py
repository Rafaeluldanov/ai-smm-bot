"""Клиент Яндекс Диска (REST API).

Использует публичный REST API Яндекс Диска (``cloud-api.yandex.net``) и OAuth-токен
из настроек (``YANDEX_DISK_TOKEN``). Токен в коде не хранится.

На Этапе 2 клиент умеет только читать: получить список ресурсов в папке,
рекурсивно собрать файлы и получить ссылку для скачивания. Скачивание файла
целиком на этом этапе не выполняется.

Реальные сетевые запросы происходят только при вызове методов. Для тестов в
конструктор можно передать ``transport`` (например, ``httpx.MockTransport``),
поэтому реальный API не дёргается.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://cloud-api.yandex.net/v1/disk"

# Расширения фото/видео для определения медиафайлов в публичной папке.
_MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".heic",
    ".bmp",
    ".tiff",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".m4v",
)


class YandexDiskError(Exception):
    """Базовая ошибка работы с Яндекс Диском."""


class YandexDiskAuthError(YandexDiskError):
    """Проблема аутентификации (нет токена или токен отклонён)."""


class YandexDiskNotFoundError(YandexDiskError):
    """Запрошенный ресурс на Яндекс Диске не найден (404)."""


def _parse_datetime(value: Any) -> datetime | None:
    """Разобрать ISO-дату из ответа API (или вернуть None)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(slots=True)
class YandexDiskResource:
    """Ресурс Яндекс Диска: файл или папка."""

    name: str
    path: str
    type: str
    mime_type: str | None = None
    size: int | None = None
    modified: datetime | None = None
    public_url: str | None = None

    @property
    def is_file(self) -> bool:
        return self.type == "file"

    @property
    def is_dir(self) -> bool:
        return self.type == "dir"

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "YandexDiskResource":
        """Построить ресурс из элемента ответа API."""
        size = data.get("size")
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            type=str(data.get("type", "")),
            mime_type=data.get("mime_type"),
            size=int(size) if isinstance(size, int) else None,
            modified=_parse_datetime(data.get("modified")),
            public_url=data.get("public_url"),
        )


class YandexDiskClient:
    """Доступ к Яндекс Диску только на чтение (Этап 2)."""

    def __init__(
        self,
        token: str | None,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise YandexDiskAuthError(
                "YANDEX_DISK_TOKEN не задан — операции с Яндекс Диском недоступны"
            )
        return {"Authorization": f"OAuth {self._token}", "Accept": "application/json"}

    def _build_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    def _request(self, method: str, url: str, params: dict[str, Any]) -> dict[str, Any]:
        headers = self._headers()
        try:
            with self._build_client() as client:
                response = client.request(method, url, params=params, headers=headers)
        except httpx.HTTPError as exc:  # сетевые/транспортные ошибки
            raise YandexDiskError(f"Сетевая ошибка запроса к Яндекс Диску: {exc}") from exc

        if response.status_code == 404:
            raise YandexDiskNotFoundError(f"Ресурс не найден: {params.get('path')}")
        if response.status_code in (401, 403):
            raise YandexDiskAuthError(f"Яндекс Диск отклонил токен (HTTP {response.status_code})")
        if response.status_code >= 400:
            raise YandexDiskError(
                f"Яндекс Диск вернул HTTP {response.status_code}: {response.text}"
            )

        payload: dict[str, Any] = response.json()
        return payload

    def list_resources(
        self, path: str, limit: int = 1000, offset: int = 0
    ) -> list[YandexDiskResource]:
        """Вернуть содержимое папки (один уровень) как список ресурсов."""
        data = self._request("GET", "/resources", {"path": path, "limit": limit, "offset": offset})
        embedded = data.get("_embedded") or {}
        items = embedded.get("items") or []
        return [YandexDiskResource.from_api(item) for item in items]

    def list_files_recursive(self, path: str, max_depth: int = 3) -> list[YandexDiskResource]:
        """Рекурсивно собрать ТОЛЬКО файлы из папки и её подпапок."""
        files: list[YandexDiskResource] = []
        self._collect_files(path, max_depth, files)
        return files

    def _collect_files(
        self, path: str, remaining_depth: int, acc: list[YandexDiskResource]
    ) -> None:
        for resource in self.list_resources(path):
            if resource.is_file:
                acc.append(resource)
            elif resource.is_dir and remaining_depth > 0:
                self._collect_files(resource.path, remaining_depth - 1, acc)

    def get_download_url(self, path: str) -> str:
        """Получить временную ссылку для скачивания файла по запросу."""
        data = self._request("GET", "/resources/download", {"path": path})
        href = data.get("href")
        if not href:
            raise YandexDiskError("Ответ Яндекс Диска не содержит href для скачивания")
        return str(href)


@dataclass(slots=True)
class YandexDiskPublicResource:
    """Ресурс публичного Яндекс Диска (файл или папка). Без OAuth-токена."""

    name: str
    path: str
    type: str
    mime_type: str | None = None
    size: int | None = None
    modified: datetime | None = None
    public_key: str | None = None
    preview: str | None = None
    file: str | None = None
    media_type: str | None = None
    embedded: list["YandexDiskPublicResource"] = field(default_factory=list)

    @property
    def is_file(self) -> bool:
        return self.type == "file"

    @property
    def is_dir(self) -> bool:
        return self.type == "dir"

    @property
    def is_media(self) -> bool:
        """Является ли ресурс фото или видео (по media_type / mime / расширению)."""
        if self.media_type in {"image", "video"}:
            return True
        if self.mime_type and (
            self.mime_type.startswith("image/") or self.mime_type.startswith("video/")
        ):
            return True
        lowered = self.name.lower()
        return any(lowered.endswith(ext) for ext in _MEDIA_EXTENSIONS)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "YandexDiskPublicResource":
        """Построить ресурс из элемента ответа public API."""
        size = data.get("size")
        embedded_raw = (data.get("_embedded") or {}).get("items") or []
        return cls(
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            type=str(data.get("type", "")),
            mime_type=data.get("mime_type"),
            size=int(size) if isinstance(size, int) else None,
            modified=_parse_datetime(data.get("modified")),
            public_key=data.get("public_key"),
            preview=data.get("preview"),
            file=data.get("file"),
            media_type=data.get("media_type"),
            embedded=[cls.from_api(item) for item in embedded_raw],
        )


class YandexDiskPublicClient:
    """Чтение публичного ресурса Яндекс Диска по публичной ссылке (без токена).

    Использует public-эндпоинты ``/public/resources`` и
    ``/public/resources/download``. OAuth-токен не требуется. В тестах в
    конструктор передаётся ``transport`` (``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def _build_client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            transport=self._transport,
        )

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._build_client() as client:
                response = client.request(
                    "GET", url, params=params, headers={"Accept": "application/json"}
                )
        except httpx.HTTPError as exc:
            raise YandexDiskError(f"Сетевая ошибка запроса к Яндекс Диску: {exc}") from exc

        if response.status_code == 404:
            raise YandexDiskNotFoundError(f"Публичный ресурс не найден: {params.get('path')}")
        if response.status_code >= 400:
            raise YandexDiskError(
                f"Яндекс Диск вернул HTTP {response.status_code}: {response.text}"
            )

        payload: dict[str, Any] = response.json()
        return payload

    def list_public_resources(
        self, public_key: str, path: str | None = None, limit: int = 100, offset: int = 0
    ) -> list[YandexDiskPublicResource]:
        """Вернуть содержимое публичной папки (один уровень)."""
        params: dict[str, Any] = {"public_key": public_key, "limit": limit, "offset": offset}
        if path is not None:
            params["path"] = path
        data = self._request("/public/resources", params)
        embedded = data.get("_embedded") or {}
        items = embedded.get("items") or []
        return [YandexDiskPublicResource.from_api(item) for item in items]

    def list_public_files_recursive(
        self, public_key: str, path: str | None = None, max_depth: int = 5
    ) -> list[YandexDiskPublicResource]:
        """Рекурсивно собрать ТОЛЬКО файлы из публичной папки и её подпапок."""
        files: list[YandexDiskPublicResource] = []
        self._collect_public_files(public_key, path, max_depth, files)
        return files

    def _collect_public_files(
        self,
        public_key: str,
        path: str | None,
        remaining_depth: int,
        acc: list[YandexDiskPublicResource],
    ) -> None:
        for resource in self.list_public_resources(public_key, path):
            if resource.is_file:
                acc.append(resource)
            elif resource.is_dir and remaining_depth > 0:
                self._collect_public_files(public_key, resource.path, remaining_depth - 1, acc)

    def get_public_download_url(self, public_key: str, path: str | None = None) -> str:
        """Получить ссылку для скачивания файла из публичного ресурса."""
        params: dict[str, Any] = {"public_key": public_key}
        if path is not None:
            params["path"] = path
        data = self._request("/public/resources/download", params)
        href = data.get("href")
        if not href:
            raise YandexDiskError("Ответ Яндекс Диска не содержит href для скачивания")
        return str(href)
