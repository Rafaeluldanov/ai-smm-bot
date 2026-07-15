"""Тесты сценариев и Decision Score (v0.7.4).

score = impact × (confidence/100) − risk penalty → 0..100; лучший = максимальный score;
предпочтения владельца повышают risk-aversion; select/reject меняют лишь статус.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import decision_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_chief_of_staff_service import AIChiefOfStaffService
from app.services.ai_decision_engine_service import AIDecisionEngineService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIDecisionEngineService:
    return AIDecisionEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _did(db: Session, pid: int, dtype: str = "sales") -> int:
    return _svc().create_decision(db, pid, decision_type=dtype, title="P")["id"]


def test_decision_score_formula() -> None:
    svc = _svc()
    # impact 80, confidence 75%, risk 20 → 80*0.75 - 0.3*20 = 60 - 6 = 54.0
    assert svc._decision_score(80, 75, 20, risk_averse=False) == 54.0
    # risk_averse: больший вес риска → ниже score
    assert svc._decision_score(80, 75, 20, risk_averse=True) < 54.0
    # clamp в [0..100]
    assert svc._decision_score(0, 0, 100, risk_averse=False) == 0.0
    assert svc._decision_score(100, 100, 0, risk_averse=False) == 100.0


def test_scenarios_evaluated_and_scored(db_session: Session) -> None:
    pid = _project(db_session, "decsc1")
    svc = _svc()
    did = _did(db_session, pid)
    svc.generate_scenarios(db_session, did)
    svc.evaluate_scenarios(db_session, did)
    scenarios = repo.list_scenarios(db_session, did)
    assert scenarios
    for s in scenarios:
        assert s.status == "evaluated"
        assert "score" in s.expected_impact


def test_recommend_picks_highest_score(db_session: Session) -> None:
    pid = _project(db_session, "decsc2")
    svc = _svc()
    did = _did(db_session, pid)
    svc.generate_scenarios(db_session, did)
    svc.evaluate_scenarios(db_session, did)
    rec = svc.recommend_best_scenario(db_session, did)
    all_scores = [
        float((s.expected_impact or {}).get("score", 0))
        for s in repo.list_scenarios(db_session, did)
        if s.status != "rejected"
    ]
    assert rec["score"] == max(all_scores)


def test_select_and_reject_scenario(db_session: Session) -> None:
    pid = _project(db_session, "decsc3")
    svc = _svc()
    did = _did(db_session, pid)
    scenarios = svc.generate_scenarios(db_session, did)
    sel = svc.select_scenario(db_session, scenarios[0]["id"])
    assert sel["status"] == "selected"
    assert repo.get_decision(db_session, did).recommended_scenario_id == scenarios[0]["id"]
    rej = svc.reject_scenario(db_session, scenarios[1]["id"])
    assert rej["status"] == "rejected"


def test_rejected_highest_scenario_excluded_from_recommendation(db_session: Session) -> None:
    """Отклоняем ЛУЧШИЙ по score сценарий → рекомендуется следующий выживший (не он)."""
    pid = _project(db_session, "decsc4")
    svc = _svc()
    did = _did(db_session, pid)
    svc.generate_scenarios(db_session, did)
    evaluated = svc.evaluate_scenarios(db_session, did)
    top = max(evaluated, key=lambda s: s["expected_impact"]["score"])
    survivors = [s for s in evaluated if s["id"] != top["id"]]
    next_best = max(survivors, key=lambda s: s["expected_impact"]["score"])
    svc.reject_scenario(db_session, top["id"])
    rec = svc.recommend_best_scenario(db_session, did)
    assert rec["scenario"]["id"] == next_best["id"]
    assert rec["score"] == next_best["expected_impact"]["score"]
    assert rec["scenario"]["id"] != top["id"]  # отклонённый лучший исключён


def test_owner_risk_aversion_lowers_risky_score(db_session: Session) -> None:
    """Одинаковый тип решения: с ограничением владельца рискованный сценарий получает ниже score."""
    svc = _svc()

    def top_risky_score(slug: str, with_restriction: bool) -> float:
        pid = _project(db_session, slug)
        if with_restriction:
            AIChiefOfStaffService(settings=_SETTINGS).save_decision_memory(
                db_session, pid, decision_type="restriction", key="sales_style",
                value={"style": "soft"},
            )
        did = _did(db_session, pid, dtype="growth")
        svc.generate_scenarios(db_session, did)
        evaluated = svc.evaluate_scenarios(db_session, did)
        # самый рискованный сценарий шаблона growth (risk=40 — «новая кампания роста»)
        risky = max(evaluated, key=lambda s: s["risk_analysis"]["risk"])
        return risky["expected_impact"]["score"]

    plain = top_risky_score("decsc5a", with_restriction=False)
    averse = top_risky_score("decsc5b", with_restriction=True)
    assert averse < plain  # предпочтения владельца реально снижают score рискового варианта


def test_reanalyze_blocked_after_accept(db_session: Session) -> None:
    """Повторный analyze на accepted/applied запрещён (не откатывает выбор владельца)."""
    from app.services.ai_decision_engine_service import AIDecisionEngineError

    pid = _project(db_session, "decsc6")
    svc = _svc()
    did = _did(db_session, pid, dtype="sales")
    svc.analyze_decision(db_session, did)
    svc.accept_decision(db_session, did)
    with pytest.raises(AIDecisionEngineError):
        svc.analyze_decision(db_session, did)


def test_selected_scenario_survives_reanalyze_and_wins(db_session: Session) -> None:
    """Явно выбранный сценарий переживает повторный analyze и остаётся рекомендованным."""
    pid = _project(db_session, "decsc7")
    svc = _svc()
    did = _did(db_session, pid, dtype="growth")
    scenarios = svc.analyze_decision(db_session, did)["scenarios"]
    # выбираем НЕ лучший по score вариант
    worst = min(scenarios, key=lambda s: s["expected_impact"]["score"])
    svc.select_scenario(db_session, worst["id"])
    out = svc.analyze_decision(db_session, did)  # повторный анализ (статус recommended)
    assert repo.get_scenario(db_session, worst["id"]).status == "selected"  # не сброшен
    assert out["decision"]["recommended_scenario_id"] == worst["id"]  # выбор владельца победил


def test_latest_selection_wins_on_reanalyze(db_session: Session) -> None:
    """Владелец передумал (A→B): только B остаётся selected, re-analyze рекомендует B."""
    pid = _project(db_session, "decsc8")
    svc = _svc()
    did = _did(db_session, pid, dtype="growth")
    scenarios = svc.analyze_decision(db_session, did)["scenarios"]
    a, b = scenarios[0]["id"], scenarios[1]["id"]
    svc.select_scenario(db_session, a)
    svc.select_scenario(db_session, b)  # передумал → B
    assert repo.get_scenario(db_session, a).status != "selected"  # прежний выбор сброшен
    assert repo.get_scenario(db_session, b).status == "selected"
    out = svc.analyze_decision(db_session, did)
    assert out["decision"]["recommended_scenario_id"] == b  # победил последний выбор


def test_reject_recommended_repoints_recommendation(db_session: Session) -> None:
    """Отклонение рекомендованного сценария переуказывает рекомендацию на выжившего."""
    pid = _project(db_session, "decsc9")
    svc = _svc()
    did = _did(db_session, pid, dtype="growth")
    rec_id = svc.analyze_decision(db_session, did)["decision"]["recommended_scenario_id"]
    svc.reject_scenario(db_session, rec_id)
    dec = repo.get_decision(db_session, did)
    assert dec.recommended_scenario_id != rec_id
    assert repo.get_scenario(db_session, dec.recommended_scenario_id).status != "rejected"


def test_rejected_scenario_survives_reanalyze(db_session: Session) -> None:
    """Отклонённый сценарий остаётся rejected при повторном analyze и не рекомендуется."""
    pid = _project(db_session, "decsc10")
    svc = _svc()
    did = _did(db_session, pid, dtype="growth")
    scenarios = svc.analyze_decision(db_session, did)["scenarios"]
    top = max(scenarios, key=lambda s: s["expected_impact"]["score"])
    svc.reject_scenario(db_session, top["id"])
    out = svc.analyze_decision(db_session, did)
    assert repo.get_scenario(db_session, top["id"]).status == "rejected"
    assert out["decision"]["recommended_scenario_id"] != top["id"]
