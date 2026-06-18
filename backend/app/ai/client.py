"""Клиент AI-провайдера (заглушка, Этап 4–5).

Провайдер абстрагирован: конкретная модель определяется настройками
(``AI_PROVIDER``, ``AI_API_KEY``). Ключ не хранится в коде.
"""

from typing import Any

_STAGE = "Интеграция с AI-провайдером запланирована на Этапы 4–5"


class AIClient:
    """Единый интерфейс к AI-провайдеру."""

    def __init__(self, provider: str, api_key: str) -> None:
        self._provider = provider
        self._api_key = api_key

    def generate_text(self, prompt: str) -> str:
        """Сгенерировать текст по промпту."""
        raise NotImplementedError(_STAGE)

    def suggest_topics(self, prompt: str) -> list[dict[str, Any]]:
        """Предложить темы публикаций."""
        raise NotImplementedError(_STAGE)

    def analyze_image(self, image_path: str, prompt: str) -> dict[str, Any]:
        """Проанализировать изображение и вернуть структурированные теги."""
        raise NotImplementedError(_STAGE)
