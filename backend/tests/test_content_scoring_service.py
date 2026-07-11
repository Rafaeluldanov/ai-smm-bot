"""Тесты сервиса оценки контента (v0.4.0, чистый — без БД)."""

from app.services.content_scoring_service import ContentScoringService


def _svc() -> ContentScoringService:
    return ContentScoringService()


def test_analyze_text_features_detects_signals() -> None:
    f = _svc().analyze_text_features(
        "Успей заказать футболку за 990 руб! Переходи https://t.me/x #мерч #подарок"
    )
    assert f["has_cta"] is True
    assert f["has_link"] is True
    assert f["has_numbers"] is True
    assert f["hashtags_count"] == 2
    assert f["length"] > 0


def test_analyze_detects_question() -> None:
    f = _svc().analyze_text_features("Какой мерч выбрать для команды?")
    assert f["has_question"] is True


def test_scores_in_range_0_100() -> None:
    scored = _svc().score_post_against_profile(
        {"vk_text": "Заказать за 500 руб #tag", "hashtags": ["tag"]}, None
    )
    for key in ("quality_score", "predicted_engagement_score", "fit_score"):
        assert 0 <= scored[key] <= 100


def test_low_quality_generates_warnings() -> None:
    scored = _svc().score_post_against_profile({"vk_text": "коротко", "hashtags": []}, None)
    assert scored["quality_score"] < 60
    assert scored["warnings"]


def test_empty_text_zero_quality() -> None:
    scored = _svc().score_post_against_profile({"vk_text": "", "hashtags": []}, None)
    assert scored["quality_score"] == 0


def test_recommendations_generated() -> None:
    recs = _svc().recommend_post_improvements({"vk_text": "коротко", "hashtags": []}, None)
    assert any("CTA" in r or "призыв" in r for r in recs)
    assert any("хэштег" in r.lower() for r in recs)


class _FakeProfile:
    high_performing_tags = ["мерч"]
    low_performing_tags = ["спам"]
    preferred_cta = ["Заказать со скидкой"]
    rejected_cta: list[str] = []
    preferred_text_length = {"target": 200}
    forbidden_patterns: list[str] = []


def test_fit_score_rewards_profile_tags() -> None:
    with_tag = _svc().score_post_against_profile(
        {"vk_text": "Заказать со скидкой #мерч", "hashtags": ["мерч"]}, _FakeProfile()
    )
    without = _svc().score_post_against_profile(
        {"vk_text": "Просто текст #случайный", "hashtags": ["случайный"]}, _FakeProfile()
    )
    assert with_tag["fit_score"] > without["fit_score"]


def test_forbidden_pattern_penalized() -> None:
    class Prof(_FakeProfile):
        forbidden_patterns = ["бесплатно"]

    scored = _svc().score_post_against_profile(
        {"vk_text": "Раздаём бесплатно всем", "hashtags": []}, Prof()
    )
    assert any("запрещённый" in w.lower() for w in scored["warnings"])
