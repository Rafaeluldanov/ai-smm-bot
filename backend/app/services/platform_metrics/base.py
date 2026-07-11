"""Базовый интерфейс адаптеров метрик платформ (v0.4.1)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# Статусы результата получения метрик по публикации.
STATUS_IMPORTED = "imported"
STATUS_SKIPPED = "skipped"
STATUS_NO_CREDENTIALS = "no_credentials"
STATUS_LIVE_DISABLED = "live_disabled"
STATUS_API_DISABLED = "api_disabled"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class PublicationContext:
    """Лёгкий контекст публикации для адаптера (без ORM/секретов)."""

    publication_id: int
    post_id: int
    platform: str
    published_at: str | None = None
    text_length: int = 0
    hashtags_count: int = 0
    has_cta: bool = False
    has_link: bool = False
    media_count: int = 0


@dataclass(frozen=True)
class PlatformMetricResult:
    """Результат получения метрик по одной публикации."""

    publication_id: int
    post_id: int
    platform: str
    status: str
    source: str
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass(frozen=True)
class MetricsPreviewResult:
    """Превью возможности импорта метрик по площадке (без записи и без сети)."""

    platform: str
    supports_api_metrics: bool
    api_enabled: bool
    publications_available: int
    status: str
    warnings: list[str] = field(default_factory=list)


def gated_results(
    publications: list[PublicationContext],
    platform: str,
    status: str,
    message: str = "",
    source: str = "api",
) -> list[PlatformMetricResult]:
    """Собрать единообразный результат-заглушку (без сети) для всех публикаций."""
    return [
        PlatformMetricResult(
            publication_id=pub.publication_id,
            post_id=pub.post_id,
            platform=platform,
            status=status,
            source=source,
            raw_metrics={},
            message=message,
        )
        for pub in publications
    ]


class PlatformMetricsAdapter(ABC):
    """Интерфейс адаптера метрик площадки.

    Реальные внешние вызовы по умолчанию выключены. Адаптеры площадок с ``api``-режимом
    при выключенном флаге возвращают ``api_disabled``; без кредов — ``no_credentials``.
    """

    platform_key: str = "unknown"
    supports_api_metrics: bool = False

    @abstractmethod
    def preview_fetch(self, publications: list[PublicationContext]) -> MetricsPreviewResult:
        """Что можно импортировать (без записи и без сети)."""

    @abstractmethod
    def fetch_metrics(
        self,
        publications: list[PublicationContext],
        credentials: dict[str, Any] | None = None,
        period: tuple[str | None, str | None] | None = None,
    ) -> list[PlatformMetricResult]:
        """Получить метрики по публикациям (для api-режима — только при включённом флаге)."""
