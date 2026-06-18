"""Клиент VK (заглушка) и безопасный клиент публикации (Этап 7).

Используется для автопостинга. Токен — из настроек (``VK_ACCESS_TOKEN``).
"""

from typing import Any

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с VK запланирована на Этап 7"


class VKClient:
    """Доступ к VK API."""

    def __init__(self, token: str) -> None:
        self._token = token

    def publish_post(self, owner_id: int | str, text: str, media_path: str | None = None) -> Any:
        """Опубликовать запись на стене сообщества."""
        raise NotImplementedError(_STAGE)


class VKPublishingClient:
    """Безопасный клиент публикации во VK (Этап 7).

    Сеть не вызывается: без токена/группы бросает понятную ``PublishError``;
    при наличии токена живой режим всё равно отключён (подключается позже). В
    тестах вместо него используется ``FakePublishingClient``.
    """

    platform = "vk"

    def __init__(self, token: str | None = None, default_target_id: str | None = None) -> None:
        self._token = token
        self._default_target_id = default_target_id

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать запись (на Этапе 7 живой режим отключён)."""
        if not self._token:
            raise PublishError("vk", "VK_ACCESS_TOKEN не задан — публикация недоступна")
        if not (request.target_id or self._default_target_id):
            raise PublishError("vk", "Не задана группа (target_id) для публикации")
        raise PublishError(
            "vk",
            "Живой режим VK отключён на Этапе 7 — подключите реальный API позже",
        )
