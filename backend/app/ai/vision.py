"""Интерфейс AI-анализа изображений (задел на будущий этап).

ВАЖНО: на Этапе 3 реальный vision-анализ НЕ подключён. Здесь только контракт
и заглушка, чтобы следующий этап мог подставить настоящий анализатор, не меняя
вызывающий код. Никаких внешних вызовов и ключей.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class VisionAnalysisNotConfiguredError(Exception):
    """AI-анализ изображений ещё не сконфигурирован/не подключён."""


@dataclass(slots=True)
class VisionAnalysisResult:
    """Результат анализа изображения (структура на будущее)."""

    labels: list[str] = field(default_factory=list)
    objects: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    text: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class BaseVisionAnalyzer(Protocol):
    """Контракт анализатора изображений."""

    def analyze_image_metadata(
        self, image_path: str, mime_type: str | None = None
    ) -> VisionAnalysisResult:
        """Проанализировать изображение и вернуть структурированные данные."""
        ...


class StubVisionAnalyzer:
    """Заглушка: реальный AI не подключён.

    Любой вызов выбрасывает :class:`VisionAnalysisNotConfiguredError`.
    Никаких сетевых запросов и API-ключей не используется.
    """

    def analyze_image_metadata(
        self, image_path: str, mime_type: str | None = None
    ) -> VisionAnalysisResult:
        raise VisionAnalysisNotConfiguredError(
            "AI vision-анализ изображений будет реализован на следующих этапах "
            "(сейчас не подключён)"
        )
