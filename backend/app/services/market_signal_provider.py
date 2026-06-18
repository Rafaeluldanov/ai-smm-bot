"""Источник рыночных/SEO сигналов для тем.

На Этапе 4 источник СТАТИЧЕСКИЙ (без сети, Wordstat/Trends не дёргаются).
Архитектура позволяет позже подставить реальный провайдер, реализующий тот же
протокол ``BaseMarketSignalProvider``.
"""

from typing import Any, Protocol, runtime_checkable

from app.services import topic_taxonomy


@runtime_checkable
class BaseMarketSignalProvider(Protocol):
    """Контракт источника рыночных сигналов по теме/кластеру."""

    def get_signals(self, project_slug: str, topic_title: str, cluster: str) -> dict[str, Any]:
        """Вернуть сигналы (search_demand/commercial_intent/seasonality/trend/competition/seo)."""
        ...


class StaticMarketSignalProvider:
    """Статический провайдер: сигналы берутся из профиля кластера (без сети)."""

    def get_signals(self, project_slug: str, topic_title: str, cluster: str) -> dict[str, Any]:
        profile = topic_taxonomy.get_cluster_profile(cluster)
        return {
            "search_demand_score": float(profile["search_demand"]),
            "commercial_intent_score": float(profile["commercial_intent"]),
            "seasonality_score": float(profile["seasonality"]),
            "trend_score": float(profile["trend"]),
            "competition_score": float(profile["competition"]),
            "seo_keywords": list(profile["seo_keywords"]),
        }
