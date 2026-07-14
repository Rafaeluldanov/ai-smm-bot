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

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.integrations import media_attachments as ma
from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

# Минимальный валидный 1x1 JPEG для probe-загрузки (реальный файл не нужен).
_TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRof"
    "Hh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAAB"
    "AAAAAAAAAAAAAAAAAAAAA//EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAT8Af//Z"
)


def _error_info(exc: Exception) -> dict[str, Any]:
    """Безопасно извлечь код/текст ошибки VK (без токена) для probe-результата."""
    if isinstance(exc, _VkApiError):
        return {"error_code": exc.error_code, "error_msg": exc.error_msg}
    return {"error_code": None, "error_msg": str(exc)}


_STAGE = "Интеграция с VK запланирована на Этап 7"
_DEFAULT_BASE_URL = "https://api.vk.com"
_DEFAULT_API_VERSION = "5.131"
# Целое число с одним необязательным знаком (для нормализации owner_id).
_NUMERIC_RE = re.compile(r"^-?\d+$")

# VK error_code=27: групповой токен не может вызывать photos.getWallUploadServer/
# photos.saveWallPhoto. Это НЕ фатально — публикуем текст без вложения.
_GROUP_AUTH_ERROR_CODE = 27
# Коды VK, при которых загрузка фото не удалась из-за прав токена (для album/auto —
# безопасный skip вместо неясной ошибки): 27 group auth, 15 access denied, 5 auth.
_PHOTO_AUTH_ERROR_CODES = frozenset({27, 15, 5})
_GROUP_AUTH_WARNING = (
    "VK photo upload skipped: group token cannot call "
    "photos.getWallUploadServer/photos.saveWallPhoto"
)

# Предупреждение о пропуске видео в группе медиа (стабильный текст для отчётов/тестов).
_VIDEO_SKIP_WARNING = "VK video upload is not implemented; video skipped"
# Лимит фото по умолчанию в одном VK-посте с группой медиа.
_DEFAULT_MAX_GROUP_PHOTOS = 5

# Стратегии загрузки фото.
_STRATEGY_WALL = "wall"
_STRATEGY_ALBUM = "album"
_STRATEGY_AUTO = "auto"
_VALID_STRATEGIES = frozenset({_STRATEGY_WALL, _STRATEGY_ALBUM, _STRATEGY_AUTO})
_DEFAULT_ALBUM_TITLE = "AI SMM Bot uploads"

# Тип элемента для загрузки: (bytes, file_name, content_type).
_ImageItem = tuple[bytes, str, str]


@dataclass(frozen=True)
class _UploadContext:
    """Параметры загрузки фото на публикацию (стратегия/альбом/обязательность медиа)."""

    strategy: str
    album_id: str | None
    album_title: str
    require_media: bool


class _VkApiError(Exception):
    """Внутренняя ошибка VK API (несёт error_code для решения о фолбэке).

    Наружу не выходит: конвертируется в :class:`PublishError` либо обрабатывается
    как безопасный text-only фолбэк (для error_code=27).
    """

    def __init__(self, error_code: int | None, error_msg: str) -> None:
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"API ошибка {error_code}: {error_msg}")


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
        media_downloader: ma.SupportsPublicMediaDownload | None = None,
        image_processor: ma.SupportsImageConversion | None = None,
        max_group_photos: int = _DEFAULT_MAX_GROUP_PHOTOS,
        photo_upload_strategy: str = _STRATEGY_WALL,
        photo_album_id: str | None = None,
        photo_album_title: str = _DEFAULT_ALBUM_TITLE,
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
        strategy = str(photo_upload_strategy or _STRATEGY_WALL).strip().lower()
        self._photo_upload_strategy = strategy if strategy in _VALID_STRATEGIES else _STRATEGY_WALL
        self._photo_album_id = str(photo_album_id) if photo_album_id else None
        self._photo_album_title = photo_album_title or _DEFAULT_ALBUM_TITLE

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
        ctx = self._upload_context(request)
        try:
            media_items = request.payload.get("media_items") if request.payload else None
            if isinstance(media_items, list) and media_items:
                attachment, raw_extra = self._prepare_group_attachments(owner_id, media_items, ctx)
            else:
                attachment, raw_extra = self._prepare_photo_attachment(owner_id, request, ctx)
            return self._wall_post(
                owner_id, request.text, attachment=attachment, raw_extra=raw_extra
            )
        except _VkApiError as exc:
            # Ошибки VK API (кроме безопасного фолбэка 27) — в PublishError.
            raise PublishError("vk", str(exc)) from exc

    def _upload_context(self, request: PublishRequest) -> _UploadContext:
        """Собрать параметры загрузки фото. Стратегия — из конфигурации клиента
        (глобальная настройка); ``album_id``/``album_title`` может дать payload."""
        payload = request.payload or {}
        strategy = self._photo_upload_strategy
        album_id = payload.get("vk_photo_album_id") or self._photo_album_id
        album_title = str(payload.get("vk_photo_album_title") or self._photo_album_title)
        require_media = str(payload.get("media_policy") or "") == "media_group"
        return _UploadContext(
            strategy=strategy,
            album_id=str(album_id) if album_id else None,
            album_title=album_title,
            require_media=require_media,
        )

    # --- Медиа-вложение ---

    def _prepare_photo_attachment(
        self, owner_id: str, request: PublishRequest, ctx: _UploadContext
    ) -> tuple[str | None, dict[str, Any]]:
        """Загрузить одиночное фото по выбранной стратегии. Сеть только на live-пути.

        При auth-ошибке загрузки (27 для wall; 27/15/5 для album) и НЕобязательном
        медиа — text-only фолбэк с деталями в ``raw_extra``. Для обязательного медиа
        (``media_policy=media_group``) — :class:`PublishError` (см. :meth:`_upload_images`).
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
        return self._upload_images(owner_id, [(content, file_name, content_type)], [], ctx)

    # --- Группа медиа (несколько фото одним постом) ---

    def _prepare_group_attachments(
        self, owner_id: str, media_items: list[dict[str, Any]], ctx: _UploadContext
    ) -> tuple[str | None, dict[str, Any]]:
        """Подготовить несколько фото и загрузить по выбранной стратегии.

        Видео пропускаются с предупреждением. Фото — до лимита ``max_group_photos``.
        Загрузка/фолбэк — в :meth:`_upload_images` (auto: wall → album при error 27).
        """
        warnings: list[str] = []
        image_items: list[dict[str, Any]] = []
        for item in media_items:
            file_name = str(item.get("file_name") or "")
            kind = str(item.get("media_kind") or ("video" if ma.is_video(file_name) else "image"))
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

        images: list[_ImageItem] = []
        for item in image_items:
            content, file_name = self._load_item_bytes(item)
            if content is None:
                warnings.append(f"Медиа недоступно для загрузки ({file_name}) — пропущено")
                continue
            content, file_name, content_type = self._maybe_convert_heic(content, file_name)
            images.append((content, file_name, content_type))

        return self._upload_images(owner_id, images, warnings, ctx)

    def _load_item_bytes(self, item: dict[str, Any]) -> tuple[bytes | None, str]:
        """Прочитать байты одного медиа группы (локальная копия или Яндекс Диск)."""
        return ma.load_item_bytes(item, self._media_downloader)

    def _maybe_convert_heic(self, content: bytes, file_name: str) -> tuple[bytes, str, str]:
        """HEIC/HEIF → JPEG в памяти (best-effort). Оригинал не перезаписывается."""
        return ma.maybe_convert_heic(content, file_name, self._image_processor)

    @staticmethod
    def public_media_url(request: PublishRequest) -> str | None:
        """Публичный media-proxy URL как fallback-источник фото (v0.6.2), если подготовлен.

        Используется только когда нет локальной улучшенной копии и оригинала на Яндекс Диске.
        Здесь лишь ЧТЕНИЕ подготовленной ссылки (``request.media_url``); реальной отправки нет.
        """
        return request.media_url

    @staticmethod
    def _media_descriptor(request: PublishRequest) -> _MediaDescriptor | None:
        """Определить медиа для вложения из запроса (без сети/чтения файлов)."""
        attachment = request.payload.get("attachment") if request.payload else None
        attachment = attachment if isinstance(attachment, dict) else {}

        # 1. Улучшенная копия — локальный файл (приоритет).
        if request.media_path:
            name = Path(request.media_path).name
            kind = "video" if ma.is_video(name) else "image"
            return _MediaDescriptor(kind, request.media_path, None, name)

        # 2. Оригинал в публичной папке Яндекс Диска.
        disk_path = attachment.get("yandex_disk_path")
        if isinstance(disk_path, str) and disk_path.startswith(ma.PUBLIC_PREFIX):
            file_name = attachment.get("file_name") or Path(disk_path).name or "photo.jpg"
            kind = "video" if ma.is_video(str(file_name)) else "image"
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

    # --- Стратегии загрузки фото (wall / album / auto) --- #

    def _upload_images(
        self,
        owner_id: str,
        images: list[_ImageItem],
        warnings: list[str],
        ctx: _UploadContext,
    ) -> tuple[str | None, dict[str, Any]]:
        """Загрузить фото по стратегии; вернуть (attachments, raw_extra).

        Успех — ``attached_photos`` + ``upload_strategy``. Auth-ошибка: если медиа
        обязательно (``require_media``) — :class:`PublishError` (календарь не
        публикует пустой пост); иначе — text-only фолбэк с деталями в ``raw_extra``.
        """
        if not images:
            return None, ({"media_warnings": warnings} if warnings else {})

        status, payload, used = self._upload_with_strategy(owner_id, images, ctx)
        if status == "ok":
            attachments = payload
            if not attachments:
                return None, ({"media_warnings": warnings} if warnings else {})
            raw_extra: dict[str, Any] = {
                "attached_photos": attachments,
                "upload_strategy": used,
            }
            if warnings:
                raw_extra["media_warnings"] = warnings
            return ",".join(attachments), raw_extra

        # status == "skip": auth-ошибка загрузки (27 для wall; 27/15/5 для album).
        code, msg = payload
        if ctx.require_media:
            raise PublishError(
                "vk",
                f"VK photo upload failed via {used} strategy (error {code}: {msg}); "
                "пост с обязательными картинками (media_policy=media_group) НЕ публикуется "
                "text-only — исправьте стратегию/права токена.",
            )
        return None, {
            "upload_strategy": used,
            "upload_error_code": code,
            "upload_error_msg": msg,
            "media_upload_skipped": True,
            "media_upload_error_code": code,
            "media_warnings": [_GROUP_AUTH_WARNING, *warnings],
        }

    def _upload_with_strategy(
        self, owner_id: str, images: list[_ImageItem], ctx: _UploadContext
    ) -> tuple[str, Any, str]:
        """Выполнить загрузку по стратегии. Вернуть ("ok"|"skip", payload, used_strategy)."""
        if ctx.strategy == _STRATEGY_ALBUM:
            return self._try_album(owner_id, images, ctx)
        if ctx.strategy == _STRATEGY_AUTO:
            status, payload, used = self._try_wall(owner_id, images)
            if status == "ok":
                return status, payload, used
            # wall упал с error 27 → пробуем album.
            return self._try_album(owner_id, images, ctx)
        return self._try_wall(owner_id, images)

    def _try_wall(self, owner_id: str, images: list[_ImageItem]) -> tuple[str, Any, str]:
        """Wall-стратегия: 27 → безопасный skip; прочие коды — наверх (PublishError)."""
        attachments: list[str] = []
        try:
            for content, file_name, content_type in images:
                attachments.append(
                    self._upload_photo_wall(owner_id, file_name, content, content_type)
                )
        except _VkApiError as exc:
            if exc.error_code == _GROUP_AUTH_ERROR_CODE:
                return "skip", (exc.error_code, exc.error_msg), _STRATEGY_WALL
            raise
        return "ok", attachments, _STRATEGY_WALL

    def _try_album(
        self, owner_id: str, images: list[_ImageItem], ctx: _UploadContext
    ) -> tuple[str, Any, str]:
        """Album-стратегия: 27/15/5 → безопасный skip; прочие коды — наверх."""
        try:
            group_id = self._group_id(owner_id)
            album_id = self._resolve_album_id(group_id, ctx.album_id, ctx.album_title)
            attachments = [
                self._upload_photo_album(group_id, album_id, file_name, content, content_type)
                for content, file_name, content_type in images
            ]
        except _VkApiError as exc:
            if exc.error_code in _PHOTO_AUTH_ERROR_CODES:
                return "skip", (exc.error_code, exc.error_msg), _STRATEGY_ALBUM
            raise
        return "ok", attachments, _STRATEGY_ALBUM

    def _upload_photo_wall(
        self, owner_id: str, file_name: str, content: bytes, content_type: str
    ) -> str:
        """Wall: getWallUploadServer → upload → saveWallPhoto → ``photo{o}_{id}``."""
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
        self,
        upload_url: str,
        file_name: str,
        content: bytes,
        content_type: str,
        *,
        result_key: str = "photo",
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
        value = data.get(result_key)
        if not value or value in ("[]", "null"):
            raise PublishError("vk", f"upload-сервер вернул пустой {result_key} (файл отклонён)")
        return data

    # --- Album-стратегия: альбом группы --- #

    def _resolve_album_id(self, group_id: str, album_id: str | None, album_title: str) -> str:
        """Найти album_id: из настроек/payload → по названию → создать новый."""
        if album_id:
            return str(album_id)
        data = self._call_method("photos.getAlbums", {"owner_id": f"-{group_id}"})
        albums = (data.get("response") or {}).get("items") or []
        for album in albums:
            if str(album.get("title")) == album_title:
                return str(album.get("id"))
        created = self._call_method(
            "photos.createAlbum",
            {
                "title": album_title,
                "group_id": group_id,
                "privacy_view": "all",
                "privacy_comment": "all",
            },
        )
        new_id = (created.get("response") or {}).get("id")
        if new_id is None:
            raise PublishError("vk", "photos.createAlbum без id")
        return str(new_id)

    def _get_album_upload_server(self, album_id: str, group_id: str) -> str:
        data = self._call_method(
            "photos.getUploadServer", {"album_id": album_id, "group_id": group_id}
        )
        upload_url = (data.get("response") or {}).get("upload_url")
        if not upload_url:
            raise PublishError("vk", "photos.getUploadServer без upload_url")
        return str(upload_url)

    def _upload_photo_album(
        self, group_id: str, album_id: str, file_name: str, content: bytes, content_type: str
    ) -> str:
        """Album: getUploadServer → upload → photos.save → ``photo{o}_{id}``."""
        upload_url = self._get_album_upload_server(album_id, group_id)
        uploaded = self._upload_file(
            upload_url, file_name, content, content_type, result_key="photos_list"
        )
        return self._save_album_photo(album_id, group_id, uploaded)

    def _save_album_photo(self, album_id: str, group_id: str, uploaded: dict[str, Any]) -> str:
        data = self._call_method(
            "photos.save",
            {
                "album_id": album_id,
                "group_id": group_id,
                "server": uploaded.get("server"),
                "photos_list": uploaded.get("photos_list"),
                "hash": uploaded.get("hash"),
            },
        )
        saved = data.get("response") or []
        if not saved:
            raise PublishError("vk", "photos.save вернул пустой список")
        photo = saved[0]
        owner = photo.get("owner_id")
        photo_id = photo.get("id")
        if owner is None or photo_id is None:
            raise PublishError("vk", "photos.save без owner_id/id")
        return f"photo{owner}_{photo_id}"

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

    # --- Probe: какая стратегия загрузки фото работает с текущим токеном --- #

    def probe_photo_strategies(
        self,
        *,
        group_id: str | None = None,
        allow_upload: bool = False,
        image_bytes: bytes | None = None,
        album_id: str | None = None,
        album_title: str | None = None,
    ) -> dict[str, Any]:
        """Проверить wall/album стратегии. НИКОГДА не вызывает ``wall.post``.

        Без ``allow_upload`` — только безопасные read-проверки (getWallUploadServer,
        getAlbums). С ``allow_upload`` — реальная загрузка тестового 1x1 JPEG в стену
        и альбом (но БЕЗ публикации на стену). Токен не печатается ни в результат, ни
        в ошибки.
        """
        target = str(group_id) if group_id else (self._default_target_id or "")
        if not target:
            return {"error": "group_id не задан (нет --group-id и VK_DEFAULT_GROUP_ID)"}
        owner_id = self._normalize_owner(target)
        try:
            gid = self._group_id(owner_id)
        except PublishError as exc:
            return {"error": str(exc)}
        resolved_album = str(album_id) if album_id else self._photo_album_id
        resolved_title = album_title or self._photo_album_title

        result: dict[str, Any] = {"group_id": gid, "allow_upload": allow_upload}
        result["group"] = self._probe_group(gid)
        if allow_upload:
            content = image_bytes or _TINY_JPEG
            result["wall"] = self._probe_wall_upload(owner_id, content)
            result["album"] = self._probe_album_upload(gid, resolved_album, resolved_title, content)
        else:
            result["wall"] = self._probe_wall_readonly(gid)
            result["album"] = self._probe_album_readonly(gid, resolved_album, resolved_title)
        if result["wall"].get("ok"):
            recommended = _STRATEGY_WALL
        elif result["album"].get("ok"):
            recommended = _STRATEGY_ALBUM
        else:
            recommended = "none"
        result["recommended_strategy"] = recommended
        return result

    def _probe_group(self, group_id: str) -> dict[str, Any]:
        try:
            data = self._call_method("groups.getById", {"group_id": group_id})
            items = data.get("response") or []
            info = items[0] if isinstance(items, list) and items else {}
            return {"ok": True, "id": info.get("id"), "name": info.get("name")}
        except (_VkApiError, PublishError) as exc:
            return {"ok": False, **_error_info(exc)}

    def _probe_wall_readonly(self, group_id: str) -> dict[str, Any]:
        try:
            return {"ok": bool(self._get_wall_upload_server(group_id))}
        except (_VkApiError, PublishError) as exc:
            return {"ok": False, **_error_info(exc)}

    def _probe_album_readonly(
        self, group_id: str, album_id: str | None, album_title: str
    ) -> dict[str, Any]:
        try:
            if album_id:
                return {"ok": True, "album_id": str(album_id), "album_found": True}
            data = self._call_method("photos.getAlbums", {"owner_id": f"-{group_id}"})
            albums = (data.get("response") or {}).get("items") or []
            found = next((a for a in albums if str(a.get("title")) == album_title), None)
            return {
                "ok": True,
                "album_id": str(found.get("id")) if found else None,
                "album_found": found is not None,
            }
        except (_VkApiError, PublishError) as exc:
            return {"ok": False, **_error_info(exc)}

    def _probe_wall_upload(self, owner_id: str, content: bytes) -> dict[str, Any]:
        try:
            attachment = self._upload_photo_wall(owner_id, "probe.jpg", content, "image/jpeg")
            return {"ok": True, "attachment": attachment}
        except (_VkApiError, PublishError) as exc:
            return {"ok": False, **_error_info(exc)}

    def _probe_album_upload(
        self, group_id: str, album_id: str | None, album_title: str, content: bytes
    ) -> dict[str, Any]:
        try:
            resolved = self._resolve_album_id(group_id, album_id, album_title)
            attachment = self._upload_photo_album(
                group_id, resolved, "probe.jpg", content, "image/jpeg"
            )
            return {"ok": True, "attachment": attachment, "album_id": resolved}
        except (_VkApiError, PublishError) as exc:
            return {"ok": False, "album_id": album_id, **_error_info(exc)}
