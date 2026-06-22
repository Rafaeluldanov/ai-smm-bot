"""Клиент VK (заглушка) и безопасный клиент публикации.

Используется для автопостинга. Токен — из настроек (``VK_ACCESS_TOKEN``).
Реальная отправка (``wall.post``) включается ТОЛЬКО при ``live_enabled=True``
(флаг ``VK_LIVE_PUBLISHING_ENABLED``); без флага — ``PublishError`` без сети.
В тестах HTTP подменяется через ``transport`` (``httpx.MockTransport``).
"""

import re
from typing import Any

import httpx

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с VK запланирована на Этап 7"
_DEFAULT_BASE_URL = "https://api.vk.com"
_DEFAULT_API_VERSION = "5.131"
# Целое число с одним необязательным знаком (для нормализации owner_id).
_NUMERIC_RE = re.compile(r"^-?\d+$")


class VKClient:
    """Доступ к VK API."""

    def __init__(self, token: str) -> None:
        self._token = token

    def publish_post(self, owner_id: int | str, text: str, media_path: str | None = None) -> Any:
        """Опубликовать запись на стене сообщества."""
        raise NotImplementedError(_STAGE)


class VKPublishingClient:
    """Безопасный клиент публикации во VK.

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
    ) -> None:
        self._token = token
        self._default_target_id = default_target_id
        self.live_enabled = live_enabled
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout
        self._transport = transport

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать запись. Без ``live_enabled`` — PublishError без сети."""
        if not self.live_enabled:
            raise PublishError("vk", "Live publishing disabled by config")
        if not self._token:
            raise PublishError("vk", "VK_ACCESS_TOKEN не задан — публикация недоступна")
        target = request.target_id or self._default_target_id
        if not target:
            raise PublishError("vk", "Не задана группа (target_id) для публикации")
        return self._wall_post(self._normalize_owner(target), request.text)

    def _wall_post(self, owner_id: str, message: str) -> PublishResponse:
        url = f"{self._base_url}/method/wall.post"
        params = {
            "owner_id": owner_id,
            "message": message,
            "from_group": 1,
            "access_token": self._token,
            "v": self._api_version,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, data=params)
        except httpx.HTTPError as exc:
            raise PublishError("vk", f"сетевая ошибка: {exc}") from exc
        if response.status_code >= 400:
            raise PublishError("vk", f"HTTP {response.status_code}: {response.text}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise PublishError("vk", f"невалидный JSON в ответе: {response.text[:200]}") from exc
        if "error" in data:
            error = data["error"] or {}
            raise PublishError(
                "vk", f"API ошибка {error.get('error_code')}: {error.get('error_msg')}"
            )
        result = data.get("response") or {}
        post_id = result.get("post_id")
        if post_id is None:
            raise PublishError("vk", f"wall.post без post_id: {data}")
        external_url = f"https://vk.com/wall{owner_id}_{post_id}"
        return PublishResponse(external_post_id=str(post_id), external_url=external_url, raw=data)

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
