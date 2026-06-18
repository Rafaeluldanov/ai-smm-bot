"""Тесты чистых функций расчёта метрик аналитики."""

from app.services.analytics_metrics import (
    calculate_ctr,
    calculate_engagement_rate,
    calculate_engagements,
    calculate_performance_score,
    safe_rate,
)


def test_safe_rate_division_by_zero() -> None:
    assert safe_rate(5, 0) == 0.0
    assert safe_rate(0, 0) == 0.0
    assert safe_rate(5, 10) == 0.5


def test_ctr() -> None:
    assert calculate_ctr(20, 1000, 800) == 0.02
    assert calculate_ctr(0, 0, 0) == 0.0


def test_engagement_rate() -> None:
    assert calculate_engagement_rate(100, 1000, 800) == 0.1
    assert calculate_engagement_rate(0, 0, 0) == 0.0


def test_engagements() -> None:
    assert calculate_engagements(1, 2, 3, 4, 5) == 15


def test_performance_score_range() -> None:
    assert calculate_performance_score(0, 0, 0, 0, 0.0, 0.0) == 0.0
    high = calculate_performance_score(5000, 5000, 1000, 600, 0.12, 0.2)
    assert high == 100.0
    mid = calculate_performance_score(1000, 800, 80, 20, 0.02, 0.08)
    assert 0.0 < mid < 100.0
