"""Тесты сервиса нормализации метрик (v0.4.1, чистый — без БД)."""

from app.services.metrics_normalization_service import (
    SOURCE_CONFIDENCE,
    MetricsNormalizationService,
)


def _svc() -> MetricsNormalizationService:
    return MetricsNormalizationService()


def test_normalize_telegram_forwards_to_shares() -> None:
    m = _svc().normalize_platform_metrics(
        "telegram", {"views": 1000, "forwards": 12, "likes": 40, "comments": 5}, "api"
    )
    assert m.shares == 12
    assert m.reposts == 12
    # views → impressions fallback (нет reach).
    assert m.impressions == 1000
    assert m.source == "api"
    assert m.confidence_score == SOURCE_CONFIDENCE["api"]


def test_normalize_vk_reposts_to_shares() -> None:
    m = _svc().normalize_platform_metrics(
        "vk", {"reach": 800, "reposts": 4, "likes": 40, "comments": 3, "links": 20}, "manual"
    )
    assert m.shares == 4
    assert m.reach == 800
    assert m.clicks == 20


def test_normalize_instagram_saves_and_reach() -> None:
    m = _svc().normalize_platform_metrics(
        "instagram",
        {"impressions": 2000, "reach": 1500, "saved": 30, "like_count": 100, "website_clicks": 40},
        "api",
    )
    assert m.saves == 30
    assert m.reach == 1500
    assert m.clicks == 40


def test_er_from_reach_then_impressions_then_views() -> None:
    svc = _svc()
    # reach приоритетнее.
    er = svc.calculate_er({"reach": 1000, "impressions": 2000, "likes": 50})
    assert er == round(50 / 1000 * 100, 3)
    # нет reach → impressions.
    er2 = svc.calculate_er({"impressions": 2000, "likes": 40})
    assert er2 == round(40 / 2000 * 100, 3)


def test_ctr_requires_impressions() -> None:
    svc = _svc()
    assert svc.calculate_ctr({"impressions": 1000, "clicks": 20}) == 2.0
    # нет impressions → None (не 0).
    assert svc.calculate_ctr({"clicks": 20}) is None


def test_null_metrics_not_treated_as_zero() -> None:
    m = _svc().normalize_platform_metrics("telegram", {"likes": 10}, "demo")
    assert m.reach is None
    assert m.impressions is None
    assert m.er_percent is None  # нет базы → None, а не 0
    assert m.ctr_percent is None


def test_raw_sanitized_strips_secrets() -> None:
    m = _svc().normalize_platform_metrics(
        "vk",
        {"reach": 100, "access_token": "SECRET", "api_key": "K", "token": "T", "likes": 5},
        "api",
    )
    assert "access_token" not in m.raw_sanitized
    assert "api_key" not in m.raw_sanitized
    assert "token" not in m.raw_sanitized
    assert m.raw_sanitized.get("reach") == 100


def test_raw_sanitized_strips_secrets_nested_in_lists() -> None:
    # Секрет во вложенном списке словарей тоже должен быть вырезан (не стрингифицирован).
    svc = _svc()
    clean = svc.sanitize_raw({"segments": [{"access_token": "SECRET123", "reach": 10}], "views": 5})
    assert "SECRET123" not in str(clean)
    assert clean["segments"] == [{"reach": 10}]
    assert clean["views"] == 5


def test_actual_engagement_score_range() -> None:
    svc = _svc()
    score = svc.calculate_actual_engagement_score(
        {"reach": 1000, "likes": 100, "comments": 20, "shares": 30, "saves": 40}
    )
    assert 0 <= score <= 100


def test_merge_prefers_higher_confidence_source() -> None:
    svc = _svc()
    merged = svc.merge_metrics(
        {"reach": 500, "likes": None, "source": "demo"},
        {"reach": 1000, "likes": 50, "source": "api"},
    )
    # api перекрывает demo для известных полей.
    assert merged["reach"] == 1000
    assert merged["likes"] == 50
    assert merged["source"] == "api"


def test_merge_does_not_overwrite_known_with_none() -> None:
    svc = _svc()
    merged = svc.merge_metrics(
        {"reach": 1000, "source": "api"},
        {"reach": None, "likes": 5, "source": "demo"},
    )
    assert merged["reach"] == 1000  # api-известное не перетёрто None от demo


def test_engagement_per_1000() -> None:
    svc = _svc()
    val = svc.calculate_engagement_per_1000({"reach": 1000, "likes": 50, "comments": 10})
    assert val == round(60 / 1000 * 1000, 2)


def test_build_metrics_quality() -> None:
    svc = _svc()
    q = svc.build_metrics_quality({"reach": 100, "likes": 10}, "manual")
    assert q["source"] == "manual"
    assert q["confidence_score"] == SOURCE_CONFIDENCE["manual"]
    assert q["known_fields"] >= 2
    assert 0 <= q["completeness"] <= 1


def test_source_confidence_order() -> None:
    assert (
        SOURCE_CONFIDENCE["api"]
        > SOURCE_CONFIDENCE["manual"]
        > SOURCE_CONFIDENCE["internal"]
        > SOURCE_CONFIDENCE["estimated"]
        > SOURCE_CONFIDENCE["demo"]
    )
