"""Demo-адаптер метрик: детерминированные значения без сети (v0.4.1).

Значения зависят только от id публикации/поста и контент-признаков — поэтому
воспроизводимы (стабильные тесты). Это НЕ реальные показатели: source=demo.
"""

from __future__ import annotations

from typing import Any

from app.services.platform_metrics.base import (
    STATUS_IMPORTED,
    MetricsPreviewResult,
    PlatformMetricResult,
    PlatformMetricsAdapter,
    PublicationContext,
)


class DemoMetricsAdapter(PlatformMetricsAdapter):
    """Стабильные demo-метрики (без внешних вызовов)."""

    platform_key = "demo"
    supports_api_metrics = False

    def preview_fetch(self, publications: list[PublicationContext]) -> MetricsPreviewResult:
        return MetricsPreviewResult(
            platform="demo",
            supports_api_metrics=False,
            api_enabled=False,
            publications_available=len(publications),
            status="preview",
            warnings=["Demo-метрики не являются реальными показателями площадки."],
        )

    def fetch_metrics(
        self,
        publications: list[PublicationContext],
        credentials: dict[str, Any] | None = None,
        period: tuple[str | None, str | None] | None = None,
    ) -> list[PlatformMetricResult]:
        results: list[PlatformMetricResult] = []
        for pub in publications:
            results.append(
                PlatformMetricResult(
                    publication_id=pub.publication_id,
                    post_id=pub.post_id,
                    platform=pub.platform,
                    status=STATUS_IMPORTED,
                    source="demo",
                    raw_metrics=self._demo_metrics(pub),
                    message="demo",
                )
            )
        return results

    @staticmethod
    def _seed(pub: PublicationContext) -> int:
        """Детерминированное «зерно» из id (без random)."""
        return (pub.publication_id * 2654435761 + pub.post_id * 40503 + 17) & 0x7FFFFFFF

    def _demo_metrics(self, pub: PublicationContext) -> dict[str, Any]:
        """Правдоподобные, но стабильные demo-метрики по контент-признакам."""
        seed = self._seed(pub)
        # База показов 300..2300, слегка растёт с длиной текста и наличием медиа.
        reach = 300 + (seed % 2000) + pub.media_count * 120 + min(pub.text_length, 800) // 4
        impressions = int(reach * (1.15 + (seed % 30) / 100))
        views = impressions
        # Вовлечения как доли от reach (стабильные множители по seed). Demo намеренно
        # даёт «живой» отклик (ER заметно выше нуля), чтобы демонстрировать обучение —
        # это НЕ реальные показатели (см. warnings).
        like_rate = 5 + (seed % 10)  # 5..14 %
        likes = int(reach * like_rate / 100)
        comments = max(0, int(likes * (5 + seed % 10) / 100))
        shares = int(likes * (3 + seed % 7) / 100)
        saves = int(likes * (2 + seed % 6) / 100)
        # Клики выше, если есть ссылка/CTA.
        click_rate = (2 + seed % 4) + (3 if pub.has_link else 0) + (2 if pub.has_cta else 0)
        clicks = int(impressions * click_rate / 1000)
        followers_delta = max(0, int((likes + shares) / 20))
        return {
            "reach": reach,
            "impressions": impressions,
            "views": views,
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "reposts": shares,
            "saves": saves,
            "clicks": clicks,
            "followers_delta": followers_delta,
        }
