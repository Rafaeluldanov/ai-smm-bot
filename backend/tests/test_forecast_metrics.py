"""Тесты прогнозной модели ForecastMetric — AI Business Forecasting (v0.7.6, offline).

Инварианты модели прогноза:
- нулевая база → нулевой прогноз/изменение;
- положительный импульс роста → рост; выше риск → меньше рост;
- дальний горизонт → больше изменение (компаундинг);
- forecast_value — модельная оценка (без гарантий), значения детерминированы и конечны.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    business_forecast_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.ai_business_forecasting_service import AIBusinessForecastingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIBusinessForecastingService:
    return AIBusinessForecastingService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


# --- Прямые проверки модели прогноза (чистые функции) --- #


def test_zero_baseline_gives_zero_forecast() -> None:
    fv, ch = _svc().project_metric("revenue", 0.0, 75.0, 10.0, 12)
    assert fv == 0.0 and ch == 0.0


def test_positive_growth_increases_metric() -> None:
    fv, ch = _svc().project_metric("revenue", 1000000.0, 75.0, 5.0, 12)
    assert fv > 1000000.0 and ch > 0.0


def test_higher_risk_dampens_growth() -> None:
    svc = _svc()
    _lo, low_ch = svc.project_metric("revenue", 1000000.0, 75.0, 5.0, 12)
    _hi, high_ch = svc.project_metric("revenue", 1000000.0, 75.0, 45.0, 12)
    assert high_ch < low_ch


def test_longer_horizon_larger_change() -> None:
    svc = _svc()
    _f3, ch3 = svc.project_metric("revenue", 1000000.0, 75.0, 10.0, 3)
    _f12, ch12 = svc.project_metric("revenue", 1000000.0, 75.0, 10.0, 12)
    assert ch12 > ch3


def test_responsiveness_orders_metrics() -> None:
    """Выручка растёт сильнее эффективности при равных входах."""
    svc = _svc()
    _rf, rev_ch = svc.project_metric("revenue", 1000.0, 75.0, 10.0, 12)
    _ef, eff_ch = svc.project_metric("efficiency", 1000.0, 75.0, 10.0, 12)
    assert rev_ch > eff_ch


def test_zero_growth_score_no_change() -> None:
    """Нет импульса роста → метрика не растёт."""
    fv, ch = _svc().project_metric("revenue", 1000.0, 0.0, 10.0, 12)
    assert fv == 1000.0 and ch == 0.0


def test_confidence_bounds() -> None:
    svc = _svc()
    hi = svc.calculate_confidence(
        sources_with_data=3, sources_total=3, growth_score=90, risk_penalty=0, history_count=4
    )
    lo = svc.calculate_confidence(
        sources_with_data=0, sources_total=3, growth_score=0, risk_penalty=50, history_count=0
    )
    assert 0.0 <= lo < hi <= 100.0


def test_forecast_values_are_finite(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcmet1")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    out = svc.generate_business_outlook(db_session, f["id"])
    for m in out["metrics"]:
        assert m["forecast_value"] == m["forecast_value"]  # not NaN
        assert m["forecast_value"] >= 0.0


def test_metric_rows_cover_all_business_metrics(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcmet2")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    rows = business_forecast_repository.list_metrics(db_session, f["id"])
    metrics = {r.metric for r in rows}
    assert metrics == {"revenue", "leads", "customers", "conversion", "traffic", "efficiency"}
    assert all(0.0 <= r.confidence_score <= 100.0 for r in rows)


def test_nonzero_baseline_drives_positive_projection(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """С реальными (ненулевыми) данными смежных слоёв baseline и проекция ненулевые.

    Ловит регрессию имён полей upstream (total_revenue/leads/conversion_rate/total_reach/
    health_score/workflow_progress) и проверяет деривацию customers = leads × conversion.
    """
    from types import SimpleNamespace

    pid, _ = _project(db_session, "fcmet3")

    def _state(*_a: object, **_k: object) -> dict[str, object]:
        return {
            "growth_score": 60.0,
            "revenue_state": {"total_revenue": 500000.0, "conversion_rate": 0.2},
            "sales_state": {"leads": 400},
        }

    monkeypatch.setattr(
        "app.services.ai_executive_service.AIExecutiveService.analyze_business_state", _state
    )
    monkeypatch.setattr(
        "app.services.analytics_service.AnalyticsService.get_project_summary",
        lambda *_a, **_k: SimpleNamespace(total_reach=100000, avg_engagement_rate=3.0),
    )
    monkeypatch.setattr(
        "app.repositories.operations_repository.get_latest_snapshot",
        lambda *_a, **_k: SimpleNamespace(health_score=80.0, metrics={"workflow_progress": 70.0}),
    )

    svc = _svc()
    baseline = svc.collect_business_baseline(db_session, pid)
    assert baseline["revenue"] > 0 and baseline["leads"] > 0 and baseline["conversion"] > 0
    assert baseline["traffic"] > 0 and baseline["health_score"] > 0
    # workflow_progress собирается из snapshot.metrics — пиним поле явно (ловит его переименование)
    assert baseline["workflow_progress"] == 70.0
    assert baseline["customers"] == round(400 * 0.2, 2) == 80.0
    assert baseline["_meta"]["sources_with_data"] == 3

    f = svc.create_forecast(db_session, pid, horizon="12_months")
    out = svc.generate_business_outlook(db_session, f["id"])
    by_metric = {m["metric"]: m for m in out["metrics"]}
    assert by_metric["revenue"]["forecast_value"] > by_metric["revenue"]["baseline_value"] > 0
    assert by_metric["revenue"]["change_percent"] > 0
    assert by_metric["leads"]["change_percent"] > 0
    # outlook по горизонтам растёт (12 мес > 3 мес по выручке)
    fs = out["forecast"]["forecast_state"]
    assert fs["12_months"]["revenue"] > fs["3_months"]["revenue"] > 0
