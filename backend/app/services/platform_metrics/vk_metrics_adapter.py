"""VK-адаптер метрик (v0.4.1).

Подготовлен под VK API (stats.getPostReach и т. п.), но реальные внешние вызовы
выключены (feature flag). Без user-token → no_credentials. В тестах VK API не
вызывается.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_metrics.base import (
    STATUS_API_DISABLED,
    STATUS_NO_CREDENTIALS,
    STATUS_SKIPPED,
    MetricsPreviewResult,
    PlatformMetricResult,
    PlatformMetricsAdapter,
    PublicationContext,
    gated_results,
)


class VKMetricsAdapter(PlatformMetricsAdapter):
    """Адаптер метрик VK (подготовлен под API, внешние вызовы выключены)."""

    platform_key = "vk"
    supports_api_metrics = True

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings

    def _api_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(s.platform_metrics_api_enabled and s.vk_metrics_api_enabled)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    @staticmethod
    def _has_credentials(credentials: dict[str, Any] | None) -> bool:
        creds = credentials or {}
        return bool(creds.get("token_present") or creds.get("access_token") or creds.get("token"))

    def preview_fetch(self, publications: list[PublicationContext]) -> MetricsPreviewResult:
        enabled = self._api_enabled()
        warnings: list[str] = []
        if not enabled:
            warnings.append("Реальный API метрик VK выключен (feature flag).")
        return MetricsPreviewResult(
            platform="vk",
            supports_api_metrics=True,
            api_enabled=enabled,
            publications_available=len(publications),
            status="preview" if enabled else STATUS_API_DISABLED,
            warnings=warnings,
        )

    def fetch_metrics(
        self,
        publications: list[PublicationContext],
        credentials: dict[str, Any] | None = None,
        period: tuple[str | None, str | None] | None = None,
    ) -> list[PlatformMetricResult]:
        if not self._api_enabled():
            return gated_results(
                publications, "vk", STATUS_API_DISABLED, "Реальный API метрик VK выключен."
            )
        if not self._has_credentials(credentials):
            return gated_results(
                publications,
                "vk",
                STATUS_NO_CREDENTIALS,
                "Нет user-token для VK stats — метрики недоступны.",
            )
        # Флаг включён и креды есть, но реальная интеграция не реализована — без сети.
        return gated_results(
            publications,
            "vk",
            STATUS_SKIPPED,
            "Реальная интеграция метрик VK пока не реализована.",
        )
