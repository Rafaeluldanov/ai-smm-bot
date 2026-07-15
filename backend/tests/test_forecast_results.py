"""Тесты прогнозной модели ForecastResult — AI Strategy Simulator (v0.7.5, offline).

Инварианты модели прогноза:
- нулевая база → нулевой прогноз/изменение;
- положительная база + положительный эффект → рост; выше риск → меньше рост;
- дальний горизонт → больше изменение, но меньше уверенность;
- forecast_value — модельная оценка (без гарантий), значения детерминированы.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    project_repository,
    strategy_simulation_repository,
    user_repository,
)
from app.repositories import decision_repository as decision_repo
from app.schemas.project import ProjectCreate
from app.services.ai_decision_engine_service import AIDecisionEngineService
from app.services.ai_strategy_simulator_service import AIStrategySimulatorService

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


# --- Прямые проверки модели прогноза (чистые функции) --- #


def test_zero_baseline_gives_zero_forecast() -> None:
    fv, ch = _svc()._project_metric("revenue", 0.0, 80.0, 20.0, 90)
    assert fv == 0.0 and ch == 0.0


def test_positive_impact_grows_metric() -> None:
    fv, ch = _svc()._project_metric("revenue", 1000.0, 80.0, 10.0, 90)
    assert fv > 1000.0 and ch > 0.0


def test_higher_risk_dampens_growth() -> None:
    svc = _svc()
    _low_fv, low_ch = svc._project_metric("revenue", 1000.0, 80.0, 10.0, 90)
    _high_fv, high_ch = svc._project_metric("revenue", 1000.0, 80.0, 80.0, 90)
    assert high_ch < low_ch


def test_longer_horizon_larger_change() -> None:
    svc = _svc()
    _fv30, ch30 = svc._project_metric("revenue", 1000.0, 80.0, 20.0, 30)
    _fv90, ch90 = svc._project_metric("revenue", 1000.0, 80.0, 20.0, 90)
    assert ch90 > ch30


def test_responsiveness_orders_metrics() -> None:
    """Выручка двигается сильнее эффективности при равных входах."""
    svc = _svc()
    _rf, rev_ch = svc._project_metric("revenue", 1000.0, 80.0, 20.0, 90)
    _ef, eff_ch = svc._project_metric("efficiency", 1000.0, 80.0, 20.0, 90)
    assert rev_ch > eff_ch


def test_confidence_decays_with_horizon() -> None:
    svc = _svc()
    assert svc._confidence_at_horizon(80.0, 30) >= svc._confidence_at_horizon(80.0, 90)


def test_forecast_confidence_bounds() -> None:
    svc = _svc()
    hi = svc.calculate_forecast_confidence(
        sources_with_data=3, sources_total=3, impact=90, confidence=90, risk=0
    )
    lo = svc.calculate_forecast_confidence(
        sources_with_data=0, sources_total=3, impact=0, confidence=0, risk=100
    )
    assert 0.0 <= lo < hi <= 100.0


# --- Проверки записи прогнозов через сервис --- #


def test_forecast_rows_persisted_with_periods(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcrow1")
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db_session, pid, decision_type="growth", title="Рост")["id"]
    scenarios = de.analyze_decision(db_session, did)["scenarios"]
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db_session, sim["id"])
    forecasts = strategy_simulation_repository.list_forecasts(db_session, sim["id"])
    periods = {f.period for f in forecasts}
    assert periods == {"30_days", "60_days", "90_days"}
    # confidence_score в допустимых границах
    assert all(0.0 <= f.confidence_score <= 100.0 for f in forecasts)


def test_scenario_signals_read_from_decision_scenario(db_session: Session) -> None:
    """Прогноз строится из impact/confidence/risk сценария решения."""
    pid, _ = _project(db_session, "fcrow2")
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db_session, pid, decision_type="growth", title="Рост")["id"]
    scenarios = de.analyze_decision(db_session, did)["scenarios"]
    scenario = decision_repo.get_scenario(db_session, scenarios[0]["id"])
    impact, confidence, risk = AIStrategySimulatorService._scenario_signals(scenario)
    assert impact > 0 and confidence > 0
    assert risk >= 0
