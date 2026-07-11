"""Тесты сервиса анализа экспериментов (v0.4.2, чистый — без БД)."""

from app.services.experiment_analysis_service import ExperimentAnalysisService


def _svc() -> ExperimentAnalysisService:
    return ExperimentAnalysisService()


def _variant(key: str, **kw: object) -> dict[str, object]:
    base = {
        "id": ord(key),
        "variant_key": key,
        "quality_score": 60,
        "predicted_engagement_score": 55,
        "metrics_snapshot": {},
        "variant_metadata": {},
    }
    base.update(kw)
    return base


def test_calculates_score_from_metrics() -> None:
    v = _variant("A", er_percent=12.0, ctr_percent=5.0, quality_score=70)
    r = _svc().calculate_variant_score(v)
    assert 0 <= r["total_score"] <= 100
    assert r["has_actual_metrics"] is True


def test_fallback_when_no_actual_metrics() -> None:
    v = _variant("A", quality_score=80, predicted_engagement_score=70)
    r = _svc().calculate_variant_score(v)
    assert r["has_actual_metrics"] is False
    assert r["confidence"] < 0.8


def test_higher_er_wins() -> None:
    a = _variant("A", er_percent=12.0, ctr_percent=5.0)
    b = _variant("B", er_percent=3.0, ctr_percent=1.0)
    winner = _svc().select_winner([a, b])
    assert winner["variant_key"] == "A"
    assert winner["reason"] in ("higher_er", "higher_ctr")


def test_approval_boosts_score() -> None:
    approved = _variant("A", variant_metadata={"feedback": {"approved": 3}})
    edited = _variant("B", variant_metadata={"feedback": {"edited": 3}})
    ra = _svc().calculate_variant_score(approved, feedback={"approved": 3})
    rb = _svc().calculate_variant_score(edited, feedback={"edited": 3})
    assert ra["total_score"] > rb["total_score"]


def test_explain_winner() -> None:
    a = _variant("A", er_percent=12.0, ctr_percent=5.0, quality_score=75)
    reasons = _svc().explain_winner(a, [_variant("B")])
    assert reasons
    assert any("A" in r for r in reasons)


def test_learning_updates_from_experiment() -> None:
    winner = _variant("A", cta_type="offer", angle="benefit", media_strategy="with_media")
    updates = _svc().build_learning_updates_from_experiment(
        winner, [_variant("B", cta_type="soft")]
    )
    assert updates["winner"]["cta_type"] == "offer"
    assert updates["weak_signals"]


def test_compare_sorted_desc() -> None:
    a = _variant("A", er_percent=2.0)
    b = _variant("B", er_percent=12.0)
    ranked = _svc().compare_variants([a, b])
    assert ranked[0]["variant_key"] == "B"
    assert ranked[0]["score"] >= ranked[1]["score"]


def test_scores_clamped_0_100() -> None:
    v = _variant("A", er_percent=999.0, ctr_percent=999.0, quality_score=999)
    r = _svc().calculate_variant_score(v)
    assert 0 <= r["total_score"] <= 100
