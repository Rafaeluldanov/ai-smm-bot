"""Провайдеры метрик аналитики (Этап 8).

Реальные Telegram/VK analytics API на этом этапе НЕ подключаются — только
интерфейс и детерминированный fake-провайдер для тестов/CLI. Сеть не вызывается.
"""

from typing import Protocol

from app.models.post_publication import PostPublication


class AnalyticsProviderError(Exception):
    """Ошибка получения метрик у провайдера."""


class BaseAnalyticsProvider(Protocol):
    """Интерфейс провайдера метрик публикации."""

    def fetch_post_metrics(self, post_publication: PostPublication) -> dict[str, int]:
        """Вернуть метрики публикации (словарь имя→значение)."""
        ...


class FakeAnalyticsProvider:
    """Детерминированный fake-провайдер: метрики из post_id/platform, без сети."""

    def fetch_post_metrics(self, post_publication: PostPublication) -> dict[str, int]:
        """Сгенерировать стабильные метрики по (post_id, platform)."""
        platform_weight = 1 if post_publication.platform == "telegram" else 2
        seed = post_publication.post_id * 31 + platform_weight * 7

        impressions = 1000 + (seed % 9) * 500
        reach = int(impressions * 0.8)
        views = int(impressions * 0.9)
        likes = 20 + seed % 50
        reactions = 10 + seed % 30
        comments = seed % 10
        shares = seed % 5
        saves = seed % 7
        clicks = 15 + seed % 40

        return {
            "impressions": impressions,
            "reach": reach,
            "views": views,
            "likes": likes,
            "reactions": reactions,
            "comments": comments,
            "shares": shares,
            "saves": saves,
            "clicks": clicks,
        }
