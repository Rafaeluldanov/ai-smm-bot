"""Telegram-адаптер метрик (v0.4.1).

Реальные вызовы платформы выключены (feature flag). Bot API не отдаёт полную
статистику канала напрямую — сейчас адаптер безопасно сообщает о недоступности,
не обещая недоступное. Никаких сетевых вызовов.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_metrics.base import (
    STATUS_API_DISABLED,
    STATUS_SKIPPED,
    MetricsPreviewResult,
    PlatformMetricResult,
    PlatformMetricsAdapter,
    PublicationContext,
    gated_results,
)


class TelegramMetricsAdapter(PlatformMetricsAdapter):
    """Адаптер метрик Telegram (подготовлен под API, внешние вызовы выключены)."""

    platform_key = "telegram"
    supports_api_metrics = True

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings

    def _api_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(s.platform_metrics_api_enabled and s.telegram_metrics_api_enabled)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def preview_fetch(self, publications: list[PublicationContext]) -> MetricsPreviewResult:
        enabled = self._api_enabled()
        warnings = [
            "Telegram Bot API не отдаёт полную статистику канала — метрики ограничены.",
        ]
        if not enabled:
            warnings.append("Реальный API метрик Telegram выключен (feature flag).")
        return MetricsPreviewResult(
            platform="telegram",
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
                publications,
                "telegram",
                STATUS_API_DISABLED,
                "Реальный API метрик Telegram выключен.",
            )
        # Флаг включён, но реальная интеграция не реализована — не делаем сетевых вызовов.
        return gated_results(
            publications,
            "telegram",
            STATUS_SKIPPED,
            "Реальная интеграция метрик Telegram пока не реализована.",
        )
