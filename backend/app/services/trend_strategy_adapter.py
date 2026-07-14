"""Trend-адаптер для контент-стратега (v0.6.6) — ПОКА mock.

Отдаёт «трендовые» контент-направления БЕЗ внешних API и без сети: детерминированный
курируемый список SMM-трендов. Позже сюда можно подключить реальный источник трендов,
сохранив интерфейс ``get_trending_topics`` / ``score_topic_trend``.
"""

from __future__ import annotations

from typing import Any

# Курируемые (детерминированные) тренды контента для SMM. Без внешних источников.
_TRENDS: tuple[dict[str, Any], ...] = (
    {
        "topic": "видео-обзор производства",
        "score": 0.9,
        "keywords": ("видео", "производство", "процесс", "закулисье", "как делаем"),
        "reason": "Короткие видео о процессе стабильно дают высокий охват и доверие.",
    },
    {
        "topic": "отзывы и кейсы клиентов",
        "score": 0.85,
        "keywords": ("отзыв", "кейс", "клиент", "результат", "история"),
        "reason": "Социальное доказательство усиливает конверсию и сохранения.",
    },
    {
        "topic": "экспертный разбор",
        "score": 0.75,
        "keywords": ("эксперт", "разбор", "гайд", "инструкция", "советы"),
        "reason": "Экспертный контент растит вовлечённость и авторитет бренда.",
    },
    {
        "topic": "закулисье команды",
        "score": 0.7,
        "keywords": ("команда", "закулисье", "будни", "люди", "бэкстейдж"),
        "reason": "Человеческое лицо бренда повышает лояльность аудитории.",
    },
    {
        "topic": "сезонная подборка",
        "score": 0.65,
        "keywords": ("сезон", "подборка", "новинки", "коллекция", "тренд"),
        "reason": "Сезонные подборки ловят всплески спроса и хорошо репостятся.",
    },
    {
        "topic": "интерактив и вопрос аудитории",
        "score": 0.6,
        "keywords": ("вопрос", "опрос", "интерактив", "голосование", "обсуждение"),
        "reason": "Вовлекающие механики поднимают охваты в алгоритмической ленте.",
    },
)


class TrendStrategyAdapter:
    """Источник трендов контента (mock, детерминированный, без сети)."""

    def get_trending_topics(self, project_slug: str | None = None) -> list[dict[str, Any]]:
        """Список трендовых направлений: ``[{topic, score, reason}]`` (без внешних API)."""
        return [{"topic": t["topic"], "score": t["score"], "reason": t["reason"]} for t in _TRENDS]

    def score_topic_trend(self, topic: str, project_slug: str | None = None) -> float:
        """Оценка темы по трендам (0..1): максимум по совпадению ключевых слов трендов."""
        topic_l = (topic or "").strip().lower()
        if not topic_l:
            return 0.0
        best = 0.0
        for trend in _TRENDS:
            if any(kw in topic_l for kw in trend["keywords"]) or trend["topic"] in topic_l:
                best = max(best, float(trend["score"]))
        return round(best, 3)


def get_trend_strategy_adapter() -> TrendStrategyAdapter:
    """DI-фабрика trend-адаптера стратегии."""
    return TrendStrategyAdapter()
