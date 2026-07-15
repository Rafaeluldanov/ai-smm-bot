"""Тесты безопасности AI Strategy Simulator (v0.7.5, offline).

Жёсткие инварианты (Часть 17): запрещено гарантировать прибыль, менять бизнес автоматически,
выполнять стратегии, менять деньги, запускать рекламу. Симулятор — аналитический слой:
- НЕ публикует, НЕ включает live, НЕ создаёт CRM/бюджетных изменений;
- бесплатно (0 units); секретов в ответах нет; строгая tenant isolation;
- run не меняет статус решения (не «применяет» его).
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import decision_repository as decision_repo
from app.schemas.project import ProjectCreate
from app.services.ai_decision_engine_service import AIDecisionEngineService
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    AIStrategySimulatorService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_KEYS = ("token", "secret", "password", "api_key", "access_token", "refresh_token")


def _svc() -> AIStrategySimulatorService:
    return AIStrategySimulatorService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _decision(db: Session, pid: int) -> tuple[int, list[dict]]:
    de = AIDecisionEngineService(settings=_SETTINGS)
    did = de.create_decision(db, pid, decision_type="growth", title="Рост")["id"]
    scenarios = de.analyze_decision(db, did)["scenarios"]
    return did, scenarios


def _run_full(db: Session, pid: int) -> tuple[int, int]:
    did, scenarios = _decision(db, pid)
    svc = _svc()
    sim = svc.create_simulation(db, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db, sim["id"])
    svc.compare_scenarios(db, did)
    svc.recommend_strategy(db, did)
    return did, sim["id"]


def test_billing_is_free() -> None:
    """USAGE_STRATEGY_SIMULATION и USAGE_FORECAST_REPORT стоят 0 units."""
    from app.services.billing_service import (
        ACTION_COSTS,
        USAGE_FORECAST_REPORT,
        USAGE_STRATEGY_SIMULATION,
    )

    assert ACTION_COSTS[USAGE_STRATEGY_SIMULATION] == 0
    assert ACTION_COSTS[USAGE_FORECAST_REPORT] == 0


def test_run_does_not_publish_or_go_live(db_session: Session) -> None:
    pid, _ = _project(db_session, "sec1")
    _run_full(db_session, pid)
    # Ни одной публикации/live-действия не создано.
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(PostPublication).count() == 0


def test_run_does_not_apply_decision(db_session: Session) -> None:
    """Симуляция не «применяет» решение: его статус остаётся аналитическим."""
    pid, _ = _project(db_session, "sec2")
    did, scenarios = _decision(db_session, pid)
    status_before = decision_repo.get_decision(db_session, did).status
    svc = _svc()
    sim = svc.create_simulation(db_session, pid, scenario_id=scenarios[0]["id"])
    svc.simulate_scenario(db_session, sim["id"])
    status_after = decision_repo.get_decision(db_session, did).status
    assert status_after == status_before  # решение не одобрено/не применено
    assert status_after not in ("accepted", "applied")


def test_public_views_have_no_secrets(db_session: Session) -> None:
    pid, _ = _project(db_session, "sec3")
    did, sid = _run_full(db_session, pid)
    svc = _svc()
    bundle = svc.get_simulation(db_session, sid)
    rec = svc.recommend_strategy(db_session, did)
    blobs = [str(bundle).lower(), str(rec).lower()]
    for blob in blobs:
        for key in _SECRET_KEYS:
            assert key not in blob


def test_forecast_never_guarantees_profit(db_session: Session) -> None:
    """В прогнозах/выводах явно указано, что это оценка, а не гарантия."""
    pid, _ = _project(db_session, "sec4")
    _did, sid = _run_full(db_session, pid)
    svc = _svc()
    ran = svc.get_simulation(db_session, sid)
    exp = svc.explain_forecast(db_session, sid)
    joined = " ".join(exp["reasons"]).lower()
    assert "гаранти" in joined  # «не финансовая гарантия»
    # прогнозные значения детерминированы и конечны
    for f in ran["forecast"]:
        assert f["forecast_value"] == f["forecast_value"]  # not NaN


def test_overall_score_bounded(db_session: Session) -> None:
    pid, _ = _project(db_session, "sec5")
    _did, sid = _run_full(db_session, pid)
    sim = _svc().get_simulation(db_session, sid)["simulation"]
    assert 0.0 <= sim["overall_score"] <= 100.0


def test_cross_tenant_scenario_blocked(db_session: Session) -> None:
    pid1, _ = _project(db_session, "sec6a")
    pid2, _ = _project(db_session, "sec6b")
    _did, scenarios = _decision(db_session, pid1)
    with pytest.raises(AIStrategySimulatorError):
        _svc().create_simulation(db_session, pid2, scenario_id=scenarios[0]["id"])


def test_baseline_survives_missing_layers(db_session: Session) -> None:
    """collect_baseline не падает при отсутствии данных смежных слоёв — возвращает нули."""
    pid, _ = _project(db_session, "sec7")
    baseline = _svc().collect_baseline(db_session, pid)
    for metric in ("revenue", "leads", "conversion", "traffic", "engagement", "efficiency"):
        assert metric in baseline
        assert baseline[metric] >= 0.0
    assert baseline["_meta"]["sources_total"] >= 1


def test_baseline_survives_raising_layers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение смежного слоя (исключение) НЕ роняет симуляцию — срабатывают try/except."""
    pid, _ = _project(db_session, "sec8")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr(
        "app.services.ai_executive_service.AIExecutiveService.analyze_business_state", _boom
    )
    monkeypatch.setattr(
        "app.services.analytics_service.AnalyticsService.get_project_summary", _boom
    )
    monkeypatch.setattr("app.repositories.operations_repository.get_latest_snapshot", _boom)
    monkeypatch.setattr(
        "app.services.ai_chief_of_staff_service.AIChiefOfStaffService.build_decision_context",
        _boom,
    )
    # collect_baseline не падает и возвращает нули (ни один источник не дал данных).
    baseline = _svc().collect_baseline(db_session, pid)
    for metric in ("revenue", "leads", "conversion", "traffic", "engagement", "efficiency"):
        assert baseline[metric] == 0.0
    assert baseline["_meta"]["sources_with_data"] == 0
    # Полный прогон (simulate/compare/recommend → доходит до _is_risk_averse) тоже переживает сбои.
    _run_full(db_session, pid)
