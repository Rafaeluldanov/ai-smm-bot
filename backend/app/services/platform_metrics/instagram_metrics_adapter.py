"""Instagram-адаптер метрик (v0.4.1).

Подготовлен под Instagram Graph API insights (impressions/reach/saves/…), но реальные
внешние вызовы выключены (feature flag). Требует access token + ig_user_id; без них —
no_credentials. Для метрик публичный image_url не обязателен. В тестах API не вызывается.
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


class InstagramMetricsAdapter(PlatformMetricsAdapter):
    """Адаптер метрик Instagram (подготовлен под Graph API, внешние вызовы выключены)."""

    platform_key = "instagram"
    supports_api_metrics = True

    def __init__(self, settings: Any | None = None) -> None:
        self._settings = settings

    def _api_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(s.platform_metrics_api_enabled and s.instagram_metrics_api_enabled)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    @staticmethod
    def _has_credentials(credentials: dict[str, Any] | None) -> bool:
        creds = credentials or {}
        has_token = bool(
            creds.get("token_present") or creds.get("access_token") or creds.get("token")
        )
        has_user = bool(creds.get("ig_user_id") or creds.get("external_id"))
        return has_token and has_user

    def preview_fetch(self, publications: list[PublicationContext]) -> MetricsPreviewResult:
        enabled = self._api_enabled()
        warnings: list[str] = []
        if not enabled:
            warnings.append("Реальный API insights Instagram выключен (feature flag).")
        return MetricsPreviewResult(
            platform="instagram",
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
                "instagram",
                STATUS_API_DISABLED,
                "Реальный API insights Instagram выключен.",
            )
        if not self._has_credentials(credentials):
            return gated_results(
                publications,
                "instagram",
                STATUS_NO_CREDENTIALS,
                "Нет access token / ig_user_id — insights недоступны.",
            )
        return gated_results(
            publications,
            "instagram",
            STATUS_SKIPPED,
            "Реальная интеграция insights Instagram пока не реализована.",
        )
