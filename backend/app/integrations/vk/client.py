"""Клиент VK (заглушка) и безопасный клиент публикации с загрузкой фото.

Используется для автопостинга. Токен — из настроек (``VK_ACCESS_TOKEN``).
Реальная отправка (``wall.post``) включается ТОЛЬКО при ``live_enabled=True``
(флаг ``VK_LIVE_PUBLISHING_ENABLED``); без флага — ``PublishError`` без сети.

Фото-вложение (v0.1.12): при наличии медиа клиент загружает изображение через
``photos.getWallUploadServer`` → multipart-upload → ``photos.saveWallPhoto`` и
прикрепляет ``photo{owner_id}_{id}`` к ``wall.post``. Источник байтов:
- локальный файл улучшенной копии (``PublishRequest.media_path``);
- публичная папка Яндекс Диска (``public://yandex/...``) — через инжектируемый
  загрузчик (``MediaDownloadService``).
Видео (.mov/.mp4/…) на этом этапе НЕ загружается: пост уходит текстом, а
предупреждение попадает в ``raw``.

Токен НИКОГДА не логируется и не попадает в тексты ошибок. В тестах HTTP
подменяется через ``transport`` (``httpx.MockTransport``).
"""

import re
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с VK запланирована на Этап 7"
_DEFAULT_BASE_URL = "https://api.vk.com"
_DEFAULT_API_VERSION = "5.131"
_PUBLIC_PREFIX = "public://yandex/"
# Целое число с одним необязательным знаком (для нормализации owner_id).
_NUMERIC_RE = re.compile(r"^-?\d+$")

# VK error_code=27: групповой токен не может вызывать photos.getWallUploadServer/
# photos.saveWallPhoto. Это НЕ фатально — публикуем текст без вложения.
_GROUP_AUTH_ERROR_CODE = 27
_GROUP_AUTH_WARNING = (
    "VK photo upload skipped: group token cannot call "
    "photos.getWallUploadServer/photos.saveWallPhoto"
)

# Видео пока не загружаем — только текст + предупреждение.
_VIDEO_EXTENSIONS = {"mov", "mp4", "m4v", "avi", "mkv", "webm"}
# Предупреждение о пропуске видео в группе медиа (стабильный текст для отчётов/тестов).
_VIDEO_SKIP_WARNING = "VK video upload is not implemented; video skipped"

# HEIC/HEIF: VK не принимает такой формат — конвертируем в JPEG в памяти (если
# нет готовой enhanced-копии и доступен процессор). Оригинал не перезаписывается.
_HEIC_EXTENSIONS = {"heic", "heif"}
# Лимит фото по умолчанию в одном VK-посте с группой медиа.
_DEFAULT_MAX_GROUP_PHOTOS = 5

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
    "heic": "image/heic",
    "heif": "image/heif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
}


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _is_video(name: str) -> bool:
    return _extension(name) in _VIDEO_EXTENSIONS


def _content_type(name: str) -> str:
    return _CONTENT_TYPES.get(_extension(name), "application/octet-stream")


class _VkApiError(Exception):
    """Внутренняя ошибка VK API (несёт error_code для решения о фолбэке).

    Наружу не выходит: конвертируется в :class:`PublishError` либо обрабатывается
    как безопасный text-only фолбэк (для error_code=27).
    """

    def __init__(self, error_code: int | None, error_msg: str) -> None:
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"API ошибка {error_code}: {error_msg}")


class SupportsPublicMediaDownload(Protocol):
    """Контракт загрузчика публичного медиа (структурный, для DI и тестов)."""

    def download_public_media(self, disk_path: str, file_name: str) -> Any:
        """Вернуть объект с полями ``bytes``, ``content_type``, ``file_name``."""
        ...


class SupportsImageConversion(Protocol):
    """Контракт конвертера изображений (HEIC/HEIF → JPEG в памяти)."""

    def enhance_image_bytes(
        self, image_bytes: bytes, profile: str, operations: dict[str, bool] | None = None
    ) -> Any:
        """Вернуть объект с полем ``output_bytes`` (сконвертированные байты)."""
        ...


class _MediaDescriptor:
    """Что и откуда прикреплять к посту (без обращения к сети)."""

    __slots__ = ("kind", "local_path", "disk_path", "file_name")

    def __init__(
        self, kind: str, local_path: str | None, disk_path: str | None, file_name: str
    ) -> None:
        self.kind = kind  # "image" | "video"
        self.local_path = local_path
        self.disk_path = disk_path
        self.file_name = file_name


class VKClient:
    """Доступ к VK API."""

    def __init__(self, token: str) -> None:
        self._token = token

    def publish_post(self, owner_id: int | str, text: str, media_path: str | None = None) -> Any:
        """Опубликовать запись на стене сообщества."""
        raise NotImplementedError(_STAGE)


class VKPublishingClient:
    """Безопасный клиент публикации во VK с поддержкой фото-вложения.

    Реальная отправка (``wall.post``) выполняется ТОЛЬКО при ``live_enabled=True``.
    Без флага — ``PublishError`` без сети. В тестах HTTP подменяется через
    ``transport`` либо клиент целиком заменяется ``FakePublishingClient``.
    """

    platform = "vk"

    def __init__(
        self,
        token: str | None = None,
        default_target_id: str | None = None,
        *,
        live_enabled: bool = False,
        base_url: str = _DEFAULT_BASE_URL,
        api_version: str = _DEFAULT_API_VERSION,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        media_downloader: SupportsPublicMediaDownload | None = None,
        image_processor: SupportsImageConversion | None = None,
        max_group_photos: int = _DEFAULT_MAX_GROUP_PHOTOS,
    ) -> None:
        self._token = token
        self._default_target_id = default_target_id
        self.live_enabled = live_enabled
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout
        self._transport = transport
        self._media_downloader = media_downloader
        self._image_processor = image_processor
        self._max_group_photos = max(1, int(max_group_photos))

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать запись (с фото, если есть). Без ``live_enabled`` — PublishError без сети."""
        if not self.live_enabled:
            raise PublishError("vk", "Live publishing disabled by config")
        if not self._token:
            raise PublishError("vk", "VK_ACCESS_TOKEN не задан — публикация недоступна")
        target = request.target_id or self._default_target_id
        if not target:
            raise PublishError("vk", "Не задана группа (target_id) для публикации")

        owner_id = self._normalize_owner(target)
        try:
            media_items = request.payload.get("media_items") if request.payload else None
            if isinstance(media_items, list) and media_items:
                attachment, raw_extra = self._prepare_group_attachments(owner_id, media_items)
            else:
                attachment, raw_extra = self._prepare_photo_attachment(owner_id, request)
            return self._wall_post(
                owner_id, request.text, attachment=attachment, raw_extra=raw_extra
            )
        except _VkApiError as exc:
            # Ошибки VK API (кроме безопасного фолбэка 27) — в PublishError.
            raise PublishError("vk", str(exc)) from exc

    # --- Медиа-вложение ---

    def _prepare_photo_attachment(
        self, owner_id: str, request: PublishRequest
    ) -> tuple[str | None, dict[str, Any]]:
        """Загрузить фото и вернуть (attachment, raw_extra). Сеть только на live-пути.

        При VK error_code=27 (групповой токен не может вызывать photos.*) вложение
        пропускается, публикация продолжается как text-only, а в ``raw_extra``
        добавляются ``media_upload_skipped`` / ``media_upload_error_code`` /
        ``media_warnings``. Прочие ошибки upload flow пробрасываются как
        :class:`_VkApiError`/:class:`PublishError`.
        """
        descriptor = self._media_descriptor(request)
        if descriptor is None:
            return None, {}
        if descriptor.kind == "video":
            return None, {
                "media_warnings": [
                    f"Видео-вложение ({descriptor.file_name}) не загружается на этом этапе — "
                    "опубликован только текст"
                ]
            }

        content = self._load_image_bytes(descriptor)
        if content is None:
            return None, {
                "media_warnings": [
                    f"Медиа недоступно для загрузки ({descriptor.file_name}) — "
                    "опубликован только текст"
                ]
            }

        content, file_name, content_type = self._maybe_convert_heic(content, descriptor.file_name)
        try:
            attachment = self._upload_photo(owner_id, file_name, content, content_type)
        except _VkApiError as exc:
            if exc.error_code == _GROUP_AUTH_ERROR_CODE:
                return None, {
                    "media_upload_skipped": True,
                    "media_upload_error_code": exc.error_code,
                    "media_warnings": [_GROUP_AUTH_WARNING],
                }
            raise  # прочие коды — наверх, publish_post превратит в PublishError
        return attachment, {}

    # --- Группа медиа (несколько фото одним постом) ---

    def _prepare_group_attachments(
        self, owner_id: str, media_items: list[dict[str, Any]]
    ) -> tuple[str | None, dict[str, Any]]:
        """Загрузить несколько фото и вернуть (attachments, raw_extra).

        Видео пропускаются с предупреждением (VK video upload не реализован). Фото
        загружаются до лимита ``max_group_photos``; результат — comma-separated
        ``photo{owner}_{id}``. При VK error_code=27 весь пост уходит text-only
        (безопасный фолбэк группового токена); прочие коды — наверх как PublishError.
        """
        warnings: list[str] = []
        image_items: list[dict[str, Any]] = []
        for item in media_items:
            file_name = str(item.get("file_name") or "")
            kind = str(item.get("media_kind") or ("video" if _is_video(file_name) else "image"))
            if kind == "video":
                label = file_name or "video"
                warnings.append(f"{_VIDEO_SKIP_WARNING} ({label})")
            else:
                image_items.append(item)

        if not image_items:
            return None, ({"media_warnings": warnings} if warnings else {})

        if len(image_items) > self._max_group_photos:
            warnings.append(
                f"VK лимит вложений: загружаем первые {self._max_group_photos} "
                f"из {len(image_items)} фото"
            )
            image_items = image_items[: self._max_group_photos]

        attachments: list[str] = []
        try:
            for item in image_items:
                content, file_name = self._load_item_bytes(item)
                if content is None:
                    warnings.append(f"Медиа недоступно для загрузки ({file_name}) — пропущено")
                    continue
                content, file_name, content_type = self._maybe_convert_heic(content, file_name)
                attachments.append(self._upload_photo(owner_id, file_name, content, content_type))
        except _VkApiError as exc:
            if exc.error_code == _GROUP_AUTH_ERROR_CODE:
                return None, {
                    "media_upload_skipped": True,
                    "media_upload_error_code": exc.error_code,
                    "media_warnings": [_GROUP_AUTH_WARNING, *warnings],
                }
            raise  # прочие коды — наверх, publish_post превратит в PublishError

        if not attachments:
            return None, ({"media_warnings": warnings} if warnings else {})

        raw_extra: dict[str, Any] = {"attached_photos": attachments}
        if warnings:
            raw_extra["media_warnings"] = warnings
        return ",".join(attachments), raw_extra

    def _load_item_bytes(self, item: dict[str, Any]) -> tuple[bytes | None, str]:
        """Прочитать байты одного медиа группы (локальная копия или Яндекс Диск)."""
        media_path = item.get("media_path")
        if isinstance(media_path, str) and media_path:
            path = Path(media_path)
            if not path.is_file():
                return None, path.name
            return path.read_bytes(), path.name

        disk_path = item.get("yandex_disk_path")
        file_name = str(
            item.get("file_name")
            or (Path(disk_path).name if isinstance(disk_path, str) else "")
            or "photo.jpg"
        )
        if (
            isinstance(disk_path, str)
            and disk_path.startswith(_PUBLIC_PREFIX)
            and self._media_downloader is not None
        ):
            downloaded = self._media_downloader.download_public_media(disk_path, file_name)
            data: bytes = downloaded.bytes
            return data, file_name
        return None, file_name

    def _maybe_convert_heic(self, content: bytes, file_name: str) -> tuple[bytes, str, str]:
        """HEIC/HEIF → JPEG в памяти (best-effort). Оригинал не перезаписывается.

        Если формат не HEIC/HEIF или процессор недоступен/не смог сконвертировать —
        возвращаем исходные байты (публикацию не роняем).
        """
        if _extension(file_name) not in _HEIC_EXTENSIONS or self._image_processor is None:
            return content, file_name, _content_type(file_name)
        try:
            result = self._image_processor.enhance_image_bytes(content, "minimal")
            converted: bytes = result.output_bytes
        except Exception:  # noqa: BLE001 — любая ошибка конвертации → грузим оригинал
            return content, file_name, _content_type(file_name)
        stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        return converted, f"{stem}.jpg", "image/jpeg"

    @staticmethod
    def _media_descriptor(request: PublishRequest) -> _MediaDescriptor | None:
        """Определить медиа для вложения из запроса (без сети/чтения файлов)."""
        attachment = request.payload.get("attachment") if request.payload else None
        attachment = attachment if isinstance(attachment, dict) else {}

        # 1. Улучшенная копия — локальный файл (приоритет).
        if request.media_path:
            name = Path(request.media_path).name
            kind = "video" if _is_video(name) else "image"
            return _MediaDescriptor(kind, request.media_path, None, name)

        # 2. Оригинал в публичной папке Яндекс Диска.
        disk_path = attachment.get("yandex_disk_path")
        if isinstance(disk_path, str) and disk_path.startswith(_PUBLIC_PREFIX):
            file_name = attachment.get("file_name") or Path(disk_path).name or "photo.jpg"
            kind = "video" if _is_video(str(file_name)) else "image"
            return _MediaDescriptor(kind, None, disk_path, str(file_name))

        return None

    def _load_image_bytes(self, descriptor: _MediaDescriptor) -> bytes | None:
        """Прочитать байты изображения (локальный файл или публичный Яндекс Диск)."""
        if descriptor.local_path is not None:
            path = Path(descriptor.local_path)
            if not path.is_file():
                return None
            return path.read_bytes()

        if descriptor.disk_path is not None and self._media_downloader is not None:
            downloaded = self._media_downloader.download_public_media(
                descriptor.disk_path, descriptor.file_name
            )
            data: bytes = downloaded.bytes
            return data

        return None

    def _upload_photo(
        self, owner_id: str, file_name: str, content: bytes, content_type: str
    ) -> str:
        """Загрузить фото на стену сообщества и вернуть attachment ``photo{o}_{id}``."""
        group_id = self._group_id(owner_id)
        upload_url = self._get_wall_upload_server(group_id)
        uploaded = self._upload_file(upload_url, file_name, content, content_type)
        return self._save_wall_photo(group_id, uploaded)

    def _get_wall_upload_server(self, group_id: str) -> str:
        data = self._call_method("photos.getWallUploadServer", {"group_id": group_id})
        response = data.get("response") or {}
        upload_url = response.get("upload_url")
        if not upload_url:
            raise PublishError("vk", "photos.getWallUploadServer без upload_url")
        return str(upload_url)

    def _upload_file(
        self, upload_url: str, file_name: str, content: bytes, content_type: str
    ) -> dict[str, Any]:
        files = {"photo": (file_name, content, content_type)}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(upload_url, files=files)
        except httpx.HTTPError as exc:
            raise PublishError("vk", f"сетевая ошибка при загрузке фото: {exc}") from exc
        if response.status_code >= 400:
            raise PublishError("vk", f"загрузка фото HTTP {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PublishError("vk", "невалидный JSON от upload-сервера") from exc
        photo = data.get("photo")
        if not photo or photo in ("[]", "null"):
            raise PublishError("vk", "upload-сервер вернул пустой photo (файл отклонён)")
        return data

    def _save_wall_photo(self, group_id: str, uploaded: dict[str, Any]) -> str:
        data = self._call_method(
            "photos.saveWallPhoto",
            {
                "group_id": group_id,
                "photo": uploaded.get("photo"),
                "server": uploaded.get("server"),
                "hash": uploaded.get("hash"),
            },
        )
        saved = data.get("response") or []
        if not saved:
            raise PublishError("vk", "photos.saveWallPhoto вернул пустой список")
        photo = saved[0]
        photo_owner = photo.get("owner_id")
        photo_id = photo.get("id")
        if photo_owner is None or photo_id is None:
            raise PublishError("vk", "photos.saveWallPhoto без owner_id/id")
        return f"photo{photo_owner}_{photo_id}"

    # --- wall.post ---

    def _wall_post(
        self,
        owner_id: str,
        message: str,
        *,
        attachment: str | None = None,
        raw_extra: dict[str, Any] | None = None,
    ) -> PublishResponse:
        params: dict[str, Any] = {"owner_id": owner_id, "message": message, "from_group": 1}
        if attachment:
            params["attachments"] = attachment
        data = self._call_method("wall.post", params)
        result = data.get("response") or {}
        post_id = result.get("post_id")
        if post_id is None:
            raise PublishError("vk", f"wall.post без post_id: {data}")
        external_url = f"https://vk.com/wall{owner_id}_{post_id}"
        raw: dict[str, Any] = dict(data)
        if attachment:
            raw["attached_photo"] = attachment
        if raw_extra:
            raw.update(raw_extra)
        return PublishResponse(external_post_id=str(post_id), external_url=external_url, raw=raw)

    # --- Низкоуровневый вызов метода VK ---

    def _call_method(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """Вызвать метод VK API. Токен добавляется здесь и НЕ попадает в ошибки."""
        url = f"{self._base_url}/method/{method}"
        full = {**params, "access_token": self._token, "v": self._api_version}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, data=full)
        except httpx.HTTPError as exc:
            raise PublishError("vk", f"сетевая ошибка ({method}): {exc}") from exc
        if response.status_code >= 400:
            raise PublishError("vk", f"{method} HTTP {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PublishError("vk", f"невалидный JSON в ответе {method}") from exc
        if "error" in data:
            error = data["error"] or {}
            raise _VkApiError(error.get("error_code"), str(error.get("error_msg")))
        return data

    @staticmethod
    def _group_id(owner_id: str) -> str:
        """Из owner_id стены (отрицательный) получить положительный group_id."""
        value = str(owner_id).strip()
        if _NUMERIC_RE.match(value):
            return str(abs(int(value)))
        raise PublishError("vk", "Не удалось определить group_id для загрузки фото")

    @staticmethod
    def _normalize_owner(target: str) -> str:
        """Стена сообщества требует ОТРИЦАТЕЛЬНЫЙ owner_id; нормализуем число.

        Некорректный таргет (например, ``--100``) НЕ нормализуем, а пробрасываем
        как есть — VK вернёт ошибку, обёрнутую в PublishError (без падения ValueError).
        """
        value = str(target).strip()
        if _NUMERIC_RE.match(value):
            number = int(value)
            return str(number if number < 0 else -number)
        return value
