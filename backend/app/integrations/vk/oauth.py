"""Низкоуровневый клиент VK OAuth (Authorization Code Flow) и вызов методов API.

Отвечает ТОЛЬКО за сетевую часть подключения пользовательского токена:
- сборка URL авторизации (``oauth.vk.com/authorize``);
- обмен ``code`` на ``access_token`` (``oauth.vk.com/access_token``);
- вызов методов VK API (``api.vk.com/method/*``) для безопасной проверки доступа.

Безопасность:
- секрет приложения (``client_secret``) и полученный ``access_token`` НИКОГДА не
  логируются и не попадают в тексты ошибок;
- сеть в тестах подменяется через ``httpx.MockTransport`` (инжектируемый
  ``transport``), поэтому реальные запросы к VK не выполняются;
- никаких публикаций: используются только read-методы (``users.get`` и т. п.) и
  ``photos.getWallUploadServer`` (возвращает upload-URL, но НЕ загружает фото).
"""

from typing import Any
from urllib.parse import urlencode

import httpx

OAUTH_AUTHORIZE_URL = "https://oauth.vk.com/authorize"
OAUTH_TOKEN_URL = "https://oauth.vk.com/access_token"
API_BASE_URL = "https://api.vk.com/method"
API_VERSION = "5.199"


class VkOAuthError(Exception):
    """Ошибка OAuth-обмена (VK вернул error / сетевой сбой). Токен НЕ раскрывается."""


class VkApiError(Exception):
    """Ошибка метода VK API (несёт ``error_code`` для интерпретации, напр. 27)."""

    def __init__(self, error_code: int | None, error_msg: str) -> None:
        self.error_code = error_code
        self.error_msg = error_msg
        super().__init__(f"VK API error {error_code}: {error_msg}")


class VkOAuthClient:
    """Сетевой клиент VK OAuth и методов API (сеть подменяется ``transport``)."""

    def __init__(
        self,
        *,
        authorize_url: str = OAUTH_AUTHORIZE_URL,
        token_url: str = OAUTH_TOKEN_URL,
        api_base_url: str = API_BASE_URL,
        api_version: str = API_VERSION,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._authorize_url = authorize_url
        self._token_url = token_url
        self._api_base_url = api_base_url.rstrip("/")
        self._api_version = api_version
        self._timeout = timeout
        self._transport = transport

    def build_authorize_url(
        self, *, client_id: str, redirect_uri: str, scope: str, state: str
    ) -> str:
        """Собрать URL авторизации VK (пользователь подтверждает доступ)."""
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "response_type": "code",
            "state": state,
            "v": self._api_version,
            "display": "page",
        }
        return f"{self._authorize_url}?{urlencode(params)}"

    def exchange_code(
        self, *, client_id: str, client_secret: str, redirect_uri: str, code: str
    ) -> dict[str, Any]:
        """Обменять ``code`` на пользовательский ``access_token``.

        Возвращает JSON VK (``access_token``/``user_id``/``expires_in``). При
        ошибке VK или сети — :class:`VkOAuthError` БЕЗ раскрытия секретов/кода.
        """
        params = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(self._token_url, params=params)
        except httpx.HTTPError as exc:
            raise VkOAuthError(f"сетевая ошибка обмена кода: {exc}") from exc
        if response.status_code >= 400:
            raise VkOAuthError(f"обмен кода: HTTP {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise VkOAuthError("невалидный JSON при обмене кода") from exc
        if "error" in data:
            # error_description может содержать техали, но НЕ секреты/токен.
            raise VkOAuthError(f"VK OAuth отклонил обмен: {data.get('error')}")
        if not data.get("access_token"):
            raise VkOAuthError("ответ VK без access_token")
        return data

    def call_method(self, method: str, token: str, params: dict[str, Any]) -> dict[str, Any]:
        """Вызвать метод VK API. Токен добавляется здесь и НЕ попадает в ошибки."""
        url = f"{self._api_base_url}/{method}"
        full = {**params, "access_token": token, "v": self._api_version}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, data=full)
        except httpx.HTTPError as exc:
            raise VkOAuthError(f"сетевая ошибка ({method}): {exc}") from exc
        if response.status_code >= 400:
            raise VkOAuthError(f"{method}: HTTP {response.status_code}")
        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            raise VkOAuthError(f"невалидный JSON в ответе {method}") from exc
        if "error" in data:
            error = data["error"] or {}
            raise VkApiError(error.get("error_code"), str(error.get("error_msg")))
        return data
