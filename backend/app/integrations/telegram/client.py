"""Клиент Telegram (заглушка) и безопасный клиент публикации с фотоальбомом.

Используется как интерфейс управления/согласования и для автопостинга. Токен — из
настроек (``TELEGRAM_BOT_TOKEN``). Реальная отправка включается ТОЛЬКО при
``live_enabled=True`` (флаг ``TELEGRAM_LIVE_PUBLISHING_ENABLED``); без флага метод
бросает ``PublishError`` и НЕ делает сетевых запросов.

Медиа-альбом (v0.1.15): если в ``PublishRequest.payload`` есть ``media_items`` с
фото, клиент скачивает изображения (локальная enhanced-копия или публичная папка
Яндекс Диска через ``media_downloader``), конвертирует HEIC/HEIF в JPEG в памяти и
отправляет альбом через ``sendMediaGroup`` (caption только в первом элементе). Одно
фото уходит через ``sendPhoto``. Видео пока НЕ загружается — пропускается с
предупреждением. Если фото недоступны — публикуется текст (``sendMessage``).

Токен НИКОГДА не логируется, не попадает в ``raw`` и тексты ошибок. В тестах HTTP
подменяется через ``transport`` (``httpx.MockTransport``).
"""

import json
from typing import Any

import httpx

from app.integrations import media_attachments as ma
from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с Telegram запланирована на Этапы 6–7"
_DEFAULT_BASE_URL = "https://api.telegram.org"
_DEFAULT_MAX_MEDIA_GROUP_PHOTOS = 10

# Видео пока не загружаем — только текст/фото + предупреждение (стабильный текст).
_VIDEO_SKIP_WARNING = "Telegram video upload is not implemented; video skipped"


class TelegramClient:
    """Доступ к Telegram Bot API."""

    def __init__(self, token: str) -> None:
        self._token = token

    def send_message(self, chat_id: int | str, text: str) -> dict[str, Any]:
        """Отправить текстовое сообщение."""
        raise NotImplementedError(_STAGE)

    def publish_post(self, channel_id: int | str, text: str, media_path: str | None = None) -> Any:
        """Опубликовать пост в канал/чат."""
        raise NotImplementedError(_STAGE)


class TelegramPublishingClient:
    """Безопасный клиент публикации в Telegram с поддержкой фотоальбома.

    Реальная отправка выполняется ТОЛЬКО при ``live_enabled=True``. Без флага —
    ``PublishError`` без сети. В тестах HTTP подменяется через ``transport`` либо
    клиент целиком заменяется ``FakePublishingClient``.
    """

    platform = "telegram"

    def __init__(
        self,
        token: str | None = None,
        default_target_id: str | None = None,
        *,
        live_enabled: bool = False,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        media_downloader: ma.SupportsPublicMediaDownload | None = None,
        image_processor: ma.SupportsImageConversion | None = None,
        max_media_group_photos: int = _DEFAULT_MAX_MEDIA_GROUP_PHOTOS,
    ) -> None:
        self._token = token
        self._default_target_id = default_target_id
        self.live_enabled = live_enabled
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._media_downloader = media_downloader
        self._image_processor = image_processor
        self._max_media_group_photos = max(1, int(max_media_group_photos))

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать пост (с фото, если есть). Без ``live_enabled`` — PublishError без сети."""
        if not self.live_enabled:
            raise PublishError("telegram", "Live publishing disabled by config")
        if not self._token:
            raise PublishError("telegram", "TELEGRAM_BOT_TOKEN не задан — публикация недоступна")
        target = request.target_id or self._default_target_id
        if not target:
            raise PublishError("telegram", "Не задан канал (target_id) для публикации")

        media_items = request.payload.get("media_items") if request.payload else None
        if isinstance(media_items, list) and media_items:
            return self._publish_media_group(
                str(target), request.text, media_items, request.payload
            )
        return self._send_message(str(target), request.text)

    # --- Текстовый пост (backward compatibility) ---

    def _send_message(self, chat_id: str, text: str) -> PublishResponse:
        parsed = self._api_call("sendMessage", json_body={"chat_id": chat_id, "text": text})
        result = parsed.get("result") or {}
        message_id = result.get("message_id")
        if message_id is None:
            raise PublishError("telegram", "sendMessage без message_id")
        return PublishResponse(
            external_post_id=str(message_id),
            external_url=self._message_url(result),
            raw=parsed,
        )

    # --- Фотоальбом (sendMediaGroup / sendPhoto) ---

    def _publish_media_group(
        self, chat_id: str, text: str, media_items: list[dict[str, Any]], payload: dict[str, Any]
    ) -> PublishResponse:
        """Собрать и отправить альбом фото. Видео пропускаются с предупреждением."""
        warnings: list[str] = []
        image_items: list[dict[str, Any]] = []
        for item in media_items:
            file_name = str(item.get("file_name") or "")
            kind = str(item.get("media_kind") or ("video" if ma.is_video(file_name) else "image"))
            if kind == "video":
                warnings.append(f"{_VIDEO_SKIP_WARNING} ({file_name or 'video'})")
            else:
                image_items.append(item)

        media_source = str(payload.get("media_source", "none"))
        media_kind = str(payload.get("media_kind", "none"))
        media_count = int(payload.get("media_count") or len(media_items))

        if len(image_items) > self._max_media_group_photos:
            warnings.append(
                f"Telegram лимит альбома: отправляем первые {self._max_media_group_photos} "
                f"из {len(image_items)} фото"
            )
            image_items = image_items[: self._max_media_group_photos]

        loaded: list[tuple[str, bytes, str]] = []
        for item in image_items:
            content, file_name = ma.load_item_bytes(item, self._media_downloader)
            if content is None:
                warnings.append(f"Медиа недоступно для загрузки ({file_name}) — пропущено")
                continue
            content, file_name, content_type = ma.maybe_convert_heic(
                content, file_name, self._image_processor
            )
            loaded.append((file_name, content, content_type))

        if not loaded:
            # Все фото недоступны (или только видео) — публикуем текст.
            parsed = self._api_call("sendMessage", json_body={"chat_id": chat_id, "text": text})
            raw = self._media_raw(media_source, media_kind, media_count, 0, warnings)
            raw["media_upload_skipped"] = True
            return self._response_from(parsed.get("result") or {}, raw)

        if len(loaded) == 1:
            parsed = self._send_photo(chat_id, text, loaded[0])
            result = parsed.get("result")
            message = result if isinstance(result, dict) else {}
        else:
            parsed = self._send_media_group(chat_id, text, loaded)
            result = parsed.get("result")
            message = result[0] if isinstance(result, list) and result else {}

        raw = self._media_raw(media_source, media_kind, media_count, len(loaded), warnings)
        return self._response_from(message, raw)

    def _send_photo(self, chat_id: str, text: str, item: tuple[str, bytes, str]) -> dict[str, Any]:
        file_name, content, content_type = item
        files = {"photo": (file_name, content, content_type)}
        data = {"chat_id": chat_id, "caption": text}
        return self._api_call("sendPhoto", data=data, files=files)

    def _send_media_group(
        self, chat_id: str, text: str, loaded: list[tuple[str, bytes, str]]
    ) -> dict[str, Any]:
        media: list[dict[str, Any]] = []
        files: dict[str, tuple[str, bytes, str]] = {}
        for index, (file_name, content, content_type) in enumerate(loaded):
            field = f"photo{index}"
            entry: dict[str, Any] = {"type": "photo", "media": f"attach://{field}"}
            if index == 0:  # caption — только у первого элемента альбома
                entry["caption"] = text
            media.append(entry)
            files[field] = (file_name, content, content_type)
        data = {"chat_id": chat_id, "media": json.dumps(media, ensure_ascii=False)}
        return self._api_call("sendMediaGroup", data=data, files=files)

    # --- Ответ/raw ---

    @staticmethod
    def _media_raw(
        media_source: str,
        media_kind: str,
        media_count: int,
        attached: int,
        warnings: list[str],
    ) -> dict[str, Any]:
        return {
            "media_source": media_source,
            "media_kind": media_kind,
            "media_count": media_count,
            "attached_photos_count": attached,
            "media_warnings": warnings,
        }

    def _response_from(self, message: dict[str, Any], raw: dict[str, Any]) -> PublishResponse:
        message_id = message.get("message_id")
        if message_id is None:
            raise PublishError("telegram", "ответ Telegram без message_id")
        return PublishResponse(
            external_post_id=str(message_id),
            external_url=self._message_url(message),
            raw=raw,
        )

    @staticmethod
    def _message_url(message: dict[str, Any]) -> str | None:
        chat = message.get("chat") or {}
        username = chat.get("username")
        message_id = message.get("message_id")
        return f"https://t.me/{username}/{message_id}" if username and message_id else None

    # --- Низкоуровневый вызов Bot API (токен только в URL, не в ошибках/raw) ---

    def _api_call(
        self,
        method: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/bot{self._token}/{method}"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                if files is not None:
                    response = client.post(url, data=data, files=files)
                elif json_body is not None:
                    response = client.post(url, json=json_body)
                else:
                    response = client.post(url, data=data)
        except httpx.HTTPError as exc:
            # Не подставляем текст исключения — в нём может быть URL с токеном.
            raise PublishError(
                "telegram", f"сетевая ошибка ({method}): {type(exc).__name__}"
            ) from exc
        if response.status_code >= 400:
            raise PublishError("telegram", f"{method} HTTP {response.status_code}")
        try:
            parsed: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PublishError("telegram", f"невалидный JSON в ответе {method}") from exc
        if not parsed.get("ok"):
            raise PublishError("telegram", f"API вернул ошибку: {parsed.get('description')}")
        return parsed
