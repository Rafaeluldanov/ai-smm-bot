"""Тесты статического источника рыночных сигналов."""

from app.services.market_signal_provider import (
    BaseMarketSignalProvider,
    StaticMarketSignalProvider,
)

_SCORE_KEYS = [
    "search_demand_score",
    "commercial_intent_score",
    "seasonality_score",
    "trend_score",
    "competition_score",
]


def test_signals_in_range() -> None:
    signals = StaticMarketSignalProvider().get_signals("teeon", "Футболки с логотипом", "футболки")
    for key in _SCORE_KEYS:
        assert 0.0 <= signals[key] <= 1.0
    assert signals["seo_keywords"]


def test_tshirt_demand_higher_than_jacquard() -> None:
    provider = StaticMarketSignalProvider()
    tshirt = provider.get_signals("teeon", "Футболки", "футболки")
    jacquard = provider.get_signals("teeon", "Жаккард", "жаккард")
    assert tshirt["search_demand_score"] > jacquard["search_demand_score"]


def test_provider_satisfies_protocol() -> None:
    assert isinstance(StaticMarketSignalProvider(), BaseMarketSignalProvider)


def test_unknown_cluster_uses_default() -> None:
    signals = StaticMarketSignalProvider().get_signals("teeon", "Нечто", "несуществующий")
    assert 0.0 <= signals["search_demand_score"] <= 1.0
