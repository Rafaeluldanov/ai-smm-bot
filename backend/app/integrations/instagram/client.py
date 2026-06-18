"""Клиент Instagram (заглушка, Этап 7+).

Используется для автопостинга. Токен — из настроек (``INSTAGRAM_ACCESS_TOKEN``).
"""

from typing import Any

_STAGE = "Интеграция с Instagram запланирована на Этап 7+"


class InstagramClient:
    """Доступ к Instagram Graph API."""

    def __init__(self, token: str) -> None:
        self._token = token

    def publish_post(self, account_id: int | str, caption: str, media_path: str) -> Any:
        """Опубликовать медиа с подписью."""
        raise NotImplementedError(_STAGE)
