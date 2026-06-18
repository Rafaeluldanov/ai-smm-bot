"""Реестр провайдеров внешних изображений (Этап 9).

По умолчанию доступен только ``fake``. В будущем сюда добавятся unsplash/pexels/
creative_commons. Сеть здесь не используется.
"""

from app.services.external_image_provider import BaseExternalImageProvider


class UnknownExternalImageProviderError(Exception):
    """Запрошен неизвестный провайдер внешних изображений."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Неизвестный провайдер внешних изображений: '{name}'")


class ExternalImageProviderRegistry:
    """Хранит провайдеров и выдаёт их по имени."""

    def __init__(self, providers: dict[str, BaseExternalImageProvider]) -> None:
        self._providers = dict(providers)

    def get_provider(self, name: str) -> BaseExternalImageProvider:
        """Вернуть провайдера по имени или бросить ошибку."""
        provider = self._providers.get(name)
        if provider is None:
            raise UnknownExternalImageProviderError(name)
        return provider

    def get_providers(self, names: list[str]) -> list[BaseExternalImageProvider]:
        """Вернуть известных провайдеров из списка имён (неизвестные пропускаются)."""
        return [self._providers[name] for name in names if name in self._providers]

    def get_available_providers(self) -> list[str]:
        """Список доступных провайдеров."""
        return list(self._providers)
