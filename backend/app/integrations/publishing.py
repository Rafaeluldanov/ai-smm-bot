"""Общие структуры публикации поста в соцсети (Этап 7).

Здесь — нейтральные к платформе типы запроса/ответа и фейковый клиент для
тестов. Реальные клиенты (Telegram/VK) реализуют протокол ``PublishingClient``.
Сеть в этих структурах не используется.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


class PublishError(Exception):
    """Ошибка публикации на платформе (нет токена, нет таргета, отказ API)."""

    def __init__(self, platform: str, message: str) -> None:
        self.platform = platform
        self.message = message
        super().__init__(f"[{platform}] {message}")


@dataclass
class PublishRequest:
    """Запрос на публикацию одного поста на одной платформе."""

    platform: str
    target_id: str | None
    text: str
    media_url: str | None = None
    media_path: str | None = None
    hashtags: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class PublishResponse:
    """Ответ платформы об успешной публикации."""

    external_post_id: str
    external_url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class PublishingClient(Protocol):
    """Интерфейс клиента публикации (структурный протокол)."""

    platform: str
    # Включена ли реальная отправка (для dry-run preview и диагностики).
    live_enabled: bool

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Опубликовать пост и вернуть внешний идентификатор."""
        ...


class FakePublishingClient:
    """Фейковый клиент для тестов: без сети, детерминированный ответ."""

    def __init__(
        self,
        platform: str,
        *,
        fail: bool = False,
        external_post_id: str | None = None,
        live_enabled: bool = True,
    ) -> None:
        self.platform = platform
        self.live_enabled = live_enabled
        self._fail = fail
        self._external_post_id = external_post_id or f"{platform}-fake-1"
        self.calls: list[PublishRequest] = []

    def publish_post(self, request: PublishRequest) -> PublishResponse:
        """Записать вызов и вернуть фейковый ответ (или бросить PublishError)."""
        self.calls.append(request)
        if self._fail:
            raise PublishError(self.platform, "fake failure")
        return PublishResponse(
            external_post_id=self._external_post_id,
            external_url=f"https://example.test/{self.platform}/{self._external_post_id}",
            raw={"ok": True, "platform": self.platform},
        )
