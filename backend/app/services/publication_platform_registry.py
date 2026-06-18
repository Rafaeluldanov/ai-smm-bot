"""Реестр клиентов публикации по платформам (Этап 7).

Сопоставляет имя платформы (``telegram``/``vk``) с клиентом публикации.
В проде заполняется реальными (безопасными) клиентами, в тестах — фейковыми.
"""

from app.integrations.publishing import PublishingClient


class UnknownPlatformError(Exception):
    """Запрошена неизвестная платформа публикации."""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        super().__init__(f"Неизвестная платформа публикации: '{platform}'")


class PublicationPlatformRegistry:
    """Хранит клиентов публикации и выдаёт их по имени платформы."""

    def __init__(self, clients: dict[str, PublishingClient]) -> None:
        self._clients = dict(clients)

    def get_client(self, platform: str) -> PublishingClient:
        """Вернуть клиент платформы или бросить UnknownPlatformError."""
        client = self._clients.get(platform)
        if client is None:
            raise UnknownPlatformError(platform)
        return client

    def get_available_platforms(self) -> list[str]:
        """Список поддерживаемых платформ."""
        return list(self._clients)
