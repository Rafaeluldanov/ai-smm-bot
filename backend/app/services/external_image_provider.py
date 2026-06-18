"""Провайдеры поиска внешних изображений (Этап 9).

Реальные стоки (Unsplash/Pexels/Creative Commons) НЕ подключаются — только
интерфейс и детерминированный fake-провайдер для тестов/CLI. Сеть не вызывается,
изображения не скачиваются.
"""

from dataclasses import dataclass, field
from typing import Protocol


class ExternalImageProviderError(Exception):
    """Ошибка провайдера внешних изображений."""


@dataclass
class ExternalImageProviderResult:
    """Один результат поиска у провайдера (без скачивания файла)."""

    provider: str
    source_url: str
    preview_url: str | None = None
    download_url: str | None = None
    title: str | None = None
    description: str | None = None
    author_name: str | None = None
    author_url: str | None = None
    license_name: str = "unknown"
    license_url: str | None = None
    commercial_use_allowed: bool = False
    modification_allowed: bool = False
    attribution_required: bool = False
    contains_people: bool = False
    contains_logo: bool = False
    safe_for_business: bool = False
    tags: list[str] = field(default_factory=list)


class BaseExternalImageProvider(Protocol):
    """Интерфейс провайдера поиска внешних изображений."""

    name: str

    def search(self, query: str, limit: int) -> list[ExternalImageProviderResult]:
        """Найти изображения по запросу (без сети — у реальных будет HTTP)."""
        ...


# Варианты результата: (метка, commercial, attribution, people, logo, safe, license, license_url).
_VARIANTS: list[tuple[str, bool, bool, bool, bool, bool, str, str]] = [
    (
        "процесс",
        True,
        False,
        False,
        False,
        True,
        "CC0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    (
        "изделие",
        True,
        True,
        False,
        False,
        True,
        "CC BY 4.0",
        "https://creativecommons.org/licenses/by/4.0/",
    ),
    (
        "с чужим логотипом",
        True,
        False,
        False,
        True,
        False,
        "CC0",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    (
        "некоммерческая лицензия",
        False,
        True,
        False,
        False,
        True,
        "CC BY-NC 4.0",
        "https://creativecommons.org/licenses/by-nc/4.0/",
    ),
]


class FakeExternalImageProvider:
    """Детерминированный fake-провайдер: результаты из запроса, без сети."""

    name = "fake"

    def search(self, query: str, limit: int) -> list[ExternalImageProviderResult]:
        """Вернуть до ``limit`` стабильных вариантов по запросу."""
        seed = sum(ord(char) for char in query)
        count = max(0, min(limit, len(_VARIANTS)))
        results: list[ExternalImageProviderResult] = []
        for index in range(count):
            label, commercial, attribution, people, logo, safe, lic, lic_url = _VARIANTS[index]
            base = f"https://images.fake.test/{self.name}/{seed}-{index}"
            results.append(
                ExternalImageProviderResult(
                    provider=self.name,
                    source_url=base,
                    preview_url=f"{base}/preview.jpg",
                    download_url=f"{base}/download.jpg",
                    title=f"{query} — {label}",
                    description=f"Иллюстрация по запросу «{query}» ({label}).",
                    author_name=f"Fake Author {index}",
                    author_url=f"https://images.fake.test/authors/{index}",
                    license_name=lic,
                    license_url=lic_url,
                    commercial_use_allowed=commercial,
                    modification_allowed=True,
                    attribution_required=attribution,
                    contains_people=people,
                    contains_logo=logo,
                    safe_for_business=safe,
                    tags=[query, label],
                )
            )
        return results
