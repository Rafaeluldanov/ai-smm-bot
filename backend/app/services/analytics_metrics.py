"""Чистые функции расчёта метрик аналитики (Этап 8).

Без БД, сети и AI. Все коэффициенты безопасны к делению на ноль и округляются
до 4 знаков. ``performance_score`` нормируется в диапазон 0..100.
"""

# Целевые ориентиры для нормировки score (подобраны под типичный SMM).
_VOLUME_TARGET = 2000  # охват/показы, дающие полный вклад по объёму
_ENGAGEMENT_RATE_TARGET = 0.15  # вовлечённость, дающая полный вклад
_CTR_TARGET = 0.08  # CTR, дающий полный вклад
_ENGAGEMENT_VOLUME_TARGET = 300  # абсолютные вовлечения, дающие полный вклад


def safe_rate(numerator: int, denominator: int) -> float:
    """Безопасное деление: при нулевом знаменателе возвращает 0.0 (4 знака)."""
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def calculate_engagements(
    likes: int, reactions: int, comments: int, shares: int, saves: int
) -> int:
    """Суммарные вовлечения (лайки + реакции + комментарии + репосты + сохранения)."""
    return likes + reactions + comments + shares + saves


def calculate_ctr(clicks: int, impressions: int, reach: int) -> float:
    """CTR = clicks / max(impressions, reach, 1)."""
    return safe_rate(clicks, max(impressions, reach, 1))


def calculate_engagement_rate(engagements: int, impressions: int, reach: int) -> float:
    """Engagement rate = engagements / max(reach, impressions, 1)."""
    return safe_rate(engagements, max(reach, impressions, 1))


def calculate_performance_score(
    impressions: int,
    reach: int,
    engagements: int,
    clicks: int,
    ctr: float,
    engagement_rate: float,
) -> float:
    """Свести метрики в оценку 0..100.

    Вклад: объём охвата/показов (25), engagement_rate (35), CTR (25),
    абсолютные вовлечения (15). ``clicks`` учтён через ``ctr``.
    """
    volume = max(impressions, reach)
    volume_score = min(volume / _VOLUME_TARGET, 1.0) * 25
    engagement_score = min(engagement_rate / _ENGAGEMENT_RATE_TARGET, 1.0) * 35
    ctr_score = min(ctr / _CTR_TARGET, 1.0) * 25
    engagement_volume_score = min(engagements / _ENGAGEMENT_VOLUME_TARGET, 1.0) * 15
    score = volume_score + engagement_score + ctr_score + engagement_volume_score
    return round(max(0.0, min(100.0, score)), 2)
