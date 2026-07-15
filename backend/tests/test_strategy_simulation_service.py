"""Тесты AIStrategySimulatorService — AI Strategy Simulator (v0.7.5, offline).

Инварианты:
- симуляция создаётся из сценария решения; run строит прогнозы (6 метрик × 3 горизонта);
- overall_score/уверенность считаются; статусы generated→running→completed;
- tenant isolation (чужой сценарий запрещён); аудит пишется; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
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


def _analyzed_decision(db: Session, pid: int, dtype: str = "growth") -> tuple[int, list[dict]]:
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db, pid, decision_type=dtype, title="Рост")["id"]
    scenarios = de.analyze_decision(db, did)["scenarios"]
    return did, scenarios


def test_create_simulation(db_session: Session) -> None:
    pid, uid = _project(db_session, "simsvc1")
    _did, scenarios = _analyzed_decision(db_session, pid)
    out = _svc().create_simulation(db_session, pid, scenario_id=scenarios[0]["id"], user_id=uid)
    assert out["status"] == "generated"
    assert out["scenario_id"] == scenarios[0]["id"]
    assert out["decision_id"] == _did
    assert out["overall_score"] == 0.0  # ещё не запущено


def test_create_rejects_unknown_period(db_session: Session) -> None:
    pid, _ = _project(db_session, "simsvc1b")
    _did, scenarios = _analyzed_decision(db_session, pid)
    with pytest.raises(AIStrategySimulatorError):
        _svc().create_simulation(
            db_session, pid, scenario_id=scenarios[0]["id"], simulation_period="bogus"
        )


def test_run_builds_forecasts(db_session: Session) -> None:
    pid, uid = _project(db_session, "simsvc2")
    _did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    out = svc.simulate_scenario(db_session, sim["id"], user_id=uid)
    assert out["simulation"]["status"] == "completed"
    # 6 метрик × 3 горизонта (30/60/90).
    assert len(out["forecast"]) == 18
    assert out["simulation"]["confidence_level"] in ("low", "medium", "high")
    assert 0.0 <= out["simulation"]["overall_score"] <= 100.0
    assert 0.0 <= out["confidence"] <= 100.0


def test_run_is_idempotent_on_forecast_count(db_session: Session) -> None:
    """Повторный run не дублирует прогнозы (append-only очищается перед пересчётом)."""
    pid, _ = _project(db_session, "simsvc3")
    _did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    first = svc.simulate_scenario(db_session, sim["id"])
    second = svc.simulate_scenario(db_session, sim["id"])
    assert len(first["forecast"]) == len(second["forecast"]) == 18


def test_get_simulation_bundle(db_session: Session) -> None:
    pid, _ = _project(db_session, "simsvc4")
    _did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db_session, sim["id"])
    bundle = svc.get_simulation(db_session, sim["id"])
    assert bundle["simulation"]["id"] == sim["id"]
    assert len(bundle["forecast"]) == 18


def test_explain_forecast_mentions_no_guarantee(db_session: Session) -> None:
    pid, _ = _project(db_session, "simsvc5")
    _did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db_session, sim["id"])
    exp = svc.explain_forecast(db_session, sim["id"])
    assert any("гаранти" in r.lower() for r in exp["reasons"])


def test_tenant_isolation_rejects_foreign_scenario(db_session: Session) -> None:
    pid1, _ = _project(db_session, "simsvc6a")
    pid2, _ = _project(db_session, "simsvc6b")
    _did, scenarios = _analyzed_decision(db_session, pid1)
    # Сценарий из проекта 1 нельзя симулировать под проектом 2.
    with pytest.raises(AIStrategySimulatorError):
        _svc().create_simulation(db_session, pid2, scenario_id=scenarios[0]["id"])


def test_summary_counts(db_session: Session) -> None:
    pid, _ = _project(db_session, "simsvc7")
    _did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db_session, sim["id"])
    summary = svc.get_summary(db_session, pid)
    assert summary["simulations_total"] == 1
    assert summary["simulations_completed"] == 1


def test_audit_entries_written(db_session: Session) -> None:
    """create/started/completed/compared/recommended пишут simulation.* в AuditLog."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "simsvc8")
    did, scenarios = _analyzed_decision(db_session, pid)
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"], user_id=uid)
    svc.simulate_scenario(db_session, sim["id"], user_id=uid)
    svc.compare_scenarios(db_session, did, user_id=uid)
    svc.recommend_strategy(db_session, did, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "simulation.created",
        "simulation.started",
        "simulation.completed",
        "simulation.compared",
        "simulation.recommended",
    ):
        assert expected in actions


def test_missing_simulation_raises(db_session: Session) -> None:
    with pytest.raises(AIStrategySimulatorError):
        _svc().get_simulation(db_session, 999999)


def test_missing_scenario_raises_not_found(db_session: Session) -> None:
    """Несуществующий сценарий → «не найден» (маппится API в 404)."""
    pid, _ = _project(db_session, "simsvc9")
    with pytest.raises(AIStrategySimulatorError, match="не найден"):
        _svc().create_simulation(db_session, pid, scenario_id=999999)


def test_missing_decision_raises_not_found(db_session: Session) -> None:
    """Несуществующее решение → «не найдено» на compare/recommend (маппится API в 404)."""
    svc = _svc()
    with pytest.raises(AIStrategySimulatorError, match="не найден"):
        svc.compare_scenarios(db_session, 999999)
    with pytest.raises(AIStrategySimulatorError, match="не найден"):
        svc.recommend_strategy(db_session, 999999)
