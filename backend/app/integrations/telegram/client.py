"""Клиент Telegram (заглушка) и безопасный клиент публикации.

Используется как интерфейс управления и согласования, а также для автопостинга.
Токен — из настроек (``TELEGRAM_BOT_TOKEN``). Реальная отправка включается ТОЛЬКО
при ``live_enabled=True`` (флаг ``TELEGRAM_LIVE_PUBLISHING_ENABLED``); без флага
метод бросает ``PublishError`` и не делает сетевых запросов. В тестах HTTP
подменяется через ``transport`` (``httpx.MockTransport``).
"""

from typing import Any

import httpx

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с Telegram запланирована на Этапы 6–7"
_DEFAULT_BASE_URL = "https://api.telegram.org"


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
    """Безопасный клиент публикации в Telegram.

    Реальная отправка (Bot API ``sendMessage``) выполняется ТОЛЬКО при
    ``live_enabled=True``. Без флага — ``PublishError`` без сети. В тестах HTTP
    подменяется через ``transport`` либо клиент целиком заменяется
    ``FakePublishingClient``.
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
    ) -> None:
        self._token = token
        self._default_target_id = default_target_id
        self.live_enabled = live_enabled
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать пост. Без ``live_enabled`` — PublishError без сети."""
        if not self.live_enabled:
            raise PublishError("telegram", "Live publishing disabled by config")
        if not self._token:
            raise PublishError("telegram", "TELEGRAM_BOT_TOKEN не задан — публикация недоступна")
        target = request.target_id or self._default_target_id
        if not target:
            raise PublishError("telegram", "Не задан канал (target_id) для публикации")
        return self._send_message(str(target), request.text)

    def _send_message(self, chat_id: str, text: str) -> PublishResponse:
        url = f"{self._base_url}/bot{self._token}/sendMessage"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, json={"chat_id": chat_id, "text": text})
        except httpx.HTTPError as exc:
            raise PublishError("telegram", f"сетевая ошибка: {exc}") from exc
        if response.status_code >= 400:
            raise PublishError("telegram", f"HTTP {response.status_code}: {response.text}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PublishError(
                "telegram", f"невалидный JSON в ответе: {response.text[:200]}"
            ) from exc
        if not data.get("ok"):
            raise PublishError("telegram", f"API вернул ошибку: {data.get('description')}")
        result = data.get("result") or {}
        message_id = result.get("message_id")
        if message_id is None:
            raise PublishError("telegram", f"sendMessage без message_id: {data}")
        chat = result.get("chat") or {}
        username = chat.get("username")
        external_url = f"https://t.me/{username}/{message_id}" if username else None
        return PublishResponse(
            external_post_id=str(message_id), external_url=external_url, raw=data
        )
