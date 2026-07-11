"""Адаптеры получения метрик платформ (v0.4.1).

Реальные внешние API по умолчанию ВЫКЛЮЧЕНЫ (feature flag). Demo-адаптер даёт
стабильные (детерминированные) метрики без сети; manual — отдельным endpoint.
"""

from app.services.platform_metrics.base import (
    MetricsPreviewResult,
    PlatformMetricResult,
    PlatformMetricsAdapter,
    PublicationContext,
)
from app.services.platform_metrics.demo_metrics_adapter import DemoMetricsAdapter
from app.services.platform_metrics.instagram_metrics_adapter import InstagramMetricsAdapter
from app.services.platform_metrics.telegram_metrics_adapter import TelegramMetricsAdapter
from app.services.platform_metrics.vk_metrics_adapter import VKMetricsAdapter

__all__ = [
    "DemoMetricsAdapter",
    "InstagramMetricsAdapter",
    "MetricsPreviewResult",
    "PlatformMetricResult",
    "PlatformMetricsAdapter",
    "PublicationContext",
    "TelegramMetricsAdapter",
    "VKMetricsAdapter",
    "build_metrics_adapter",
]


def build_metrics_adapter(
    platform_key: str, settings: object | None = None
) -> PlatformMetricsAdapter:
    """Построить адаптер метрик для площадки (api-адаптеры — с учётом feature flag)."""
    from app.config import get_settings

    resolved = settings or get_settings()
    platform = (platform_key or "").strip().lower()
    if platform == "telegram":
        return TelegramMetricsAdapter(settings=resolved)
    if platform == "vk":
        return VKMetricsAdapter(settings=resolved)
    if platform == "instagram":
        return InstagramMetricsAdapter(settings=resolved)
    return DemoMetricsAdapter()
