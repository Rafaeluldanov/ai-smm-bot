"""Интерфейс «умной» AI-ретуши изображений (ЗАГЛУШКА, без реального AI).

Этот модуль задаёт КОНТРАКТ для будущего этапа: удаление грязи/пятен,
выравнивание цвета ткани, улучшение текстуры, апскейл. Сейчас реальный AI НЕ
подключён — ``StubImageEditor`` намеренно бросает ``ImageEditingNotConfiguredError``
на любой вызов.

Важно (по продукту):
- Локальное автоулучшение (``ImageEnhancementProcessor``) НЕ занимается точечной
  ретушью дефектов — оно лишь безопасно корректирует свет/резкость/размер.
- Автоматическое «скрытие» дефектов товара (пятна, грязь, неровности ткани)
  потенциально вводит покупателя в заблуждение, поэтому будущая AI-ретушь
  ОБЯЗАТЕЛЬНО проходит ручной review (статус ``needs_review``), а не публикуется
  автоматически.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# Поддерживаемые типы AI-правок (для будущей реализации).
RETOUCH_OPERATIONS = (
    "remove_dirt_and_stains",
    "even_fabric_color",
    "improve_texture",
    "upscale",
)


class ImageEditingNotConfiguredError(Exception):
    """Реальный AI-редактор изображений не подключён (этап запланирован)."""

    def __init__(self, operation: str = "edit_image") -> None:
        self.operation = operation
        super().__init__(
            f"AI-ретушь '{operation}' не настроена: реальный AI пока не подключён. "
            "Используйте безопасное локальное улучшение (ImageEnhancementProcessor)."
        )


@dataclass(slots=True)
class ImageEditRequest:
    """Запрос на AI-правку изображения."""

    image_bytes: bytes
    operation: str
    instruction: str = ""
    params: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ImageEditResult:
    """Результат AI-правки изображения."""

    output_bytes: bytes
    operation: str
    requires_review: bool = True
    notes: str = ""
    warnings: list[str] = field(default_factory=list)


@runtime_checkable
class BaseImageEditor(Protocol):
    """Контракт AI-редактора изображений (реализация — на будущем этапе)."""

    def remove_dirt_and_stains(self, request: ImageEditRequest) -> ImageEditResult:
        """Удалить грязь и пятна (требует ручного review)."""
        ...

    def even_fabric_color(self, request: ImageEditRequest) -> ImageEditResult:
        """Выровнять цвет ткани (требует ручного review)."""
        ...

    def improve_texture(self, request: ImageEditRequest) -> ImageEditResult:
        """Улучшить текстуру (требует ручного review)."""
        ...

    def upscale(self, request: ImageEditRequest) -> ImageEditResult:
        """Увеличить разрешение изображения."""
        ...

    def edit_image(self, request: ImageEditRequest) -> ImageEditResult:
        """Выполнить произвольную AI-правку по инструкции."""
        ...


class StubImageEditor:
    """Заглушка AI-редактора: любой вызов бросает ImageEditingNotConfiguredError."""

    def remove_dirt_and_stains(self, request: ImageEditRequest) -> ImageEditResult:
        raise ImageEditingNotConfiguredError("remove_dirt_and_stains")

    def even_fabric_color(self, request: ImageEditRequest) -> ImageEditResult:
        raise ImageEditingNotConfiguredError("even_fabric_color")

    def improve_texture(self, request: ImageEditRequest) -> ImageEditResult:
        raise ImageEditingNotConfiguredError("improve_texture")

    def upscale(self, request: ImageEditRequest) -> ImageEditResult:
        raise ImageEditingNotConfiguredError("upscale")

    def edit_image(self, request: ImageEditRequest) -> ImageEditResult:
        raise ImageEditingNotConfiguredError(request.operation or "edit_image")
