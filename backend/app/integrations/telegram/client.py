"""Клиент Telegram (заглушка) и безопасный клиент публикации (Этап 7).

Используется как интерфейс управления и согласования, а также для автопостинга.
Токен — из настроек (``TELEGRAM_BOT_TOKEN``).
"""

from typing import Any

from app.integrations.publishing import PublishError, PublishRequest, PublishResponse

_STAGE = "Интеграция с Telegram запланирована на Этапы 6–7"


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
    """Безопасный клиент публикации в Telegram (Этап 7).

    Сеть не вызывается: без токена/канала бросает понятную ``PublishError``;
    при наличии токена живой режим всё равно отключён (подключается позже). В
    тестах вместо него используется ``FakePublishingClient``.
    """

    platform = "telegram"

    def __init__(self, token: str | None = None, default_target_id: str | None = None) -> None:
        self._token = token
        self._default_target_id = default_target_id

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать пост (на Этапе 7 живой режим отключён)."""
        if not self._token:
            raise PublishError("telegram", "TELEGRAM_BOT_TOKEN не задан — публикация недоступна")
        if not (request.target_id or self._default_target_id):
            raise PublishError("telegram", "Не задан канал (target_id) для публикации")
        raise PublishError(
            "telegram",
            "Живой режим Telegram отключён на Этапе 7 — подключите реальный API позже",
        )
