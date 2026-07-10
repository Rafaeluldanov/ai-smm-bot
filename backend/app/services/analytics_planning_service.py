"""Планирование глубокой аналитики: оценка стоимости и офлайн-превью.

Готовит для UI «Аналитика»: сколько units будет стоить отчёт выбранной глубины по
проекту/платформе/периоду и календарный офлайн-превью постов. НИКАКИХ реальных
вызовов внешних API — данные берутся из уже сохранённых снапшотов или из
детерминированного офлайн-провайдера (демо-заглушки).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.unit_economics_service import (
    ANALYTICS_DEPTHS,
    UnitEconomicsService,
    get_unit_economics_service,
)

# Периоды отчёта → число дней (для оценки и календаря).
PERIOD_DAYS: dict[str, int] = {
    "today": 1,
    "7d": 7,
    "30d": 30,
    "month": 30,
    "custom": 30,
}
DEPTHS: tuple[str, ...] = ANALYTICS_DEPTHS


@dataclass(frozen=True)
class AnalyticsEstimate:
    """Оценка стоимости аналитического отчёта (units), без списания."""

    depth: str
    period: str
    post_count: int
    estimated_units: int
    per_depth_units: dict[str, int] = field(default_factory=dict)
    live_calls: bool = False  # всегда False на этом этапе (офлайн)


class AnalyticsPlanningService:
    """Оценивает стоимость аналитики и собирает офлайн-превью (без сети)."""

    def __init__(self, economics: UnitEconomicsService | None = None) -> None:
        self._economics = economics or get_unit_economics_service()

    def estimate_report(
        self,
        depth: str = "light",
        period: str = "7d",
        post_count: int = 1,
    ) -> AnalyticsEstimate:
        """Оценить стоимость отчёта выбранной глубины (units), без вызовов API."""
        depth_norm = (depth or "light").strip().lower()
        if depth_norm not in DEPTHS:
            depth_norm = "light"
        period_norm = (period or "7d").strip().lower()
        if period_norm not in PERIOD_DAYS:
            period_norm = "7d"
        n = max(1, int(post_count or 1))
        per_depth = {d: self._economics.estimate_analytics_units(d, n) for d in DEPTHS}
        return AnalyticsEstimate(
            depth=depth_norm,
            period=period_norm,
            post_count=n,
            estimated_units=per_depth[depth_norm],
            per_depth_units=per_depth,
            live_calls=False,
        )

    def depth_price_table(self) -> list[dict[str, object]]:
        """Цены аналитики по глубине для одного поста (для UI-подсказки)."""
        return self._economics.analytics_price_table()


def get_analytics_planning_service() -> AnalyticsPlanningService:
    """DI-фабрика сервиса планирования аналитики (офлайн)."""
    return AnalyticsPlanningService()
