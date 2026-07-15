"""Тесты сравнения сценариев и рекомендации — AI Strategy Simulator (v0.7.5, offline).

Инварианты:
- compare_scenarios: победитель — максимальный Strategy Score; score_difference корректен;
- отклонённые сценарии не участвуют; сравнение сохраняется (append-only), берётся последнее;
- recommend_strategy: winner + confidence + reason; ничего не выполняет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import strategy_simulation_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_decision_engine_service import AIDecisionEngineService
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    AIStrategySimulatorService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIStrategySimulatorService:
    return AIStrategySimulatorService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _decision(db: Session, pid: int, dtype: str = "growth") -> tuple[int, list[dict]]:
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db, pid, decision_type=dtype, title="Рост")["id"]
    scenarios = de.analyze_decision(db, did)["scenarios"]
    return did, scenarios


def test_compare_picks_max_strategy_score(db_session: Session) -> None:
    pid, uid = _project(db_session, "cmp1")
    did, _sc = _decision(db_session, pid)
    out = _svc().compare_scenarios(db_session, did, user_id=uid)
    scenarios = out["comparison_data"]["scenarios"]
    scores = [s["strategy_score"] for s in scenarios]
    assert scores == sorted(scores, reverse=True)  # отсортированы по убыванию
    assert out["winner_scenario_id"] == scenarios[0]["scenario_id"]
    assert out["score_difference"] == round(scores[0] - scores[1], 1)


def test_compare_persists_and_latest_returned(db_session: Session) -> None:
    pid, _ = _project(db_session, "cmp2")
    did, _sc = _decision(db_session, pid)
    svc = _svc()
    svc.compare_scenarios(db_session, did)
    svc.compare_scenarios(db_session, did)
    comparisons = repo.list_comparisons(db_session, did)
    assert len(comparisons) == 2  # append-only
    latest = repo.get_scenario_comparison(db_session, did)
    assert latest.id == max(c.id for c in comparisons)


def test_rejected_scenarios_excluded(db_session: Session) -> None:
    pid, _ = _project(db_session, "cmp3")
    did, scenarios = _decision(db_session, pid)
    de = AIDecisionEngineService(settings=_SETTINGS)
    de.reject_scenario(db_session, scenarios[0]["id"])
    out = _svc().compare_scenarios(db_session, did)
    ids = {s["scenario_id"] for s in out["comparison_data"]["scenarios"]}
    assert scenarios[0]["id"] not in ids


def test_compare_requires_scenarios(db_session: Session) -> None:
    pid, _ = _project(db_session, "cmp4")
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db_session, pid, decision_type="growth", title="Пусто")["id"]
    # решение без анализа → сценариев нет
    with pytest.raises(AIStrategySimulatorError):
        _svc().compare_scenarios(db_session, did)


def test_recommend_returns_winner_and_reason(db_session: Session) -> None:
    pid, uid = _project(db_session, "cmp5")
    did, _sc = _decision(db_session, pid)
    rec = _svc().recommend_strategy(db_session, did, user_id=uid)
    assert rec["winner"] is not None
    assert 0.0 <= rec["winner_score"] <= 100.0
    assert rec["reason"]
    assert "совещательн" in rec["note"].lower()


def test_recommend_auto_compares_when_absent(db_session: Session) -> None:
    """recommend без предварительного compare сам строит сравнение."""
    pid, _ = _project(db_session, "cmp6")
    did, _sc = _decision(db_session, pid)
    svc = _svc()
    assert repo.get_scenario_comparison(db_session, did) is None
    svc.recommend_strategy(db_session, did)
    assert repo.get_scenario_comparison(db_session, did) is not None


def test_risk_averse_weighting_changes_scores(db_session: Session) -> None:
    """Осторожность к риску снижает Strategy Score (больше вес риска)."""
    svc = _svc()
    neutral = svc._score(80.0, 70.0, 40.0, risk_averse=False)
    averse = svc._score(80.0, 70.0, 40.0, risk_averse=True)
    assert averse < neutral


def test_single_scenario_has_zero_score_difference(db_session: Session) -> None:
    """Один сценарий → отрыва нет: score_difference = 0.0 (а не абсолютный score победителя)."""
    pid, _ = _project(db_session, "cmp7")
    did, scenarios = _decision(db_session, pid)
    de = AIDecisionEngineService(settings=_SETTINGS)
    de.reject_scenario(db_session, scenarios[1]["id"])
    de.reject_scenario(db_session, scenarios[2]["id"])
    out = _svc().compare_scenarios(db_session, did)
    assert len(out["comparison_data"]["scenarios"]) == 1
    assert out["score_difference"] == 0.0


def test_recommend_skips_scenario_rejected_after_compare(db_session: Session) -> None:
    """Если победитель сравнения отклонён позже, рекомендация не возвращает отклонённый сценарий."""
    pid, _ = _project(db_session, "cmp8")
    did, _sc = _decision(db_session, pid)
    svc = _svc()
    cmp = svc.compare_scenarios(db_session, did)
    winner_id = cmp["winner_scenario_id"]
    AIDecisionEngineService(settings=_SETTINGS).reject_scenario(db_session, winner_id)
    rec = svc.recommend_strategy(db_session, did)
    assert rec["winner"] is not None
    assert rec["winner"]["id"] != winner_id  # не отклонённый победитель
    assert rec["winner"]["status"] != "rejected"
