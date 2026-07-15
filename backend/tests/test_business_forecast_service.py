"""Тесты AIBusinessForecastingService — AI Business Forecasting Engine (v0.7.6, offline).

Инварианты:
- прогноз создаётся из состояния бизнеса; generate строит KPI (6) + outlook (3/6/12) + roadmap;
- risk_level/confidence считаются; статус generated; tenant isolation; аудит пишется; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    AIBusinessForecastingService,
)

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


def test_create_forecast(db_session: Session) -> None:
    pid, uid = _project(db_session, "fcsvc1")
    out = _svc().create_forecast(db_session, pid, horizon="12_months", user_id=uid)
    assert out["status"] == "generated"
    assert out["horizon"] == "12_months"
    assert "growth_score" in out["baseline_state"]


def test_create_rejects_unknown_horizon(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc1b")
    with pytest.raises(AIBusinessForecastingError):
        _svc().create_forecast(db_session, pid, horizon="bogus")


def test_generate_builds_metrics_outlook_roadmap(db_session: Session) -> None:
    pid, uid = _project(db_session, "fcsvc2")
    svc = _svc()
    f = svc.create_forecast(db_session, pid, horizon="12_months")
    out = svc.generate_business_outlook(db_session, f["id"], user_id=uid)
    assert len(out["metrics"]) == 6  # revenue/leads/customers/conversion/traffic/efficiency
    fs = out["forecast"]["forecast_state"]
    assert set(fs.keys()) >= {"3_months", "6_months", "12_months"}
    assert out["roadmap"] is not None and len(out["roadmap"]["quarters"]) == 4
    assert out["forecast"]["risk_level"] in ("low", "medium", "high", "critical")
    assert 0.0 <= out["confidence"] <= 100.0
    assert out["forecast"]["generated_at"] is not None


def test_generate_is_idempotent_on_metric_count(db_session: Session) -> None:
    """Повторная генерация не дублирует метрики/roadmap (append-only очищается перед пересчётом)."""
    pid, _ = _project(db_session, "fcsvc3")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    first = svc.generate_business_outlook(db_session, f["id"])
    second = svc.generate_business_outlook(db_session, f["id"])
    assert len(first["metrics"]) == len(second["metrics"]) == 6
    # roadmap не размножается
    from sqlalchemy import func

    from app.models.business_roadmap import BusinessRoadmap
    from app.repositories import business_forecast_repository as repo

    count = db_session.query(func.count(BusinessRoadmap.id)).filter_by(forecast_id=f["id"]).scalar()
    assert count == 1
    assert repo.get_roadmap(db_session, f["id"]) is not None


def test_get_forecast_bundle(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc4")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    bundle = svc.get_forecast(db_session, f["id"])
    assert bundle["forecast"]["id"] == f["id"]
    assert len(bundle["metrics"]) == 6
    assert bundle["roadmap"] is not None


def test_business_outlook_returns_latest(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc5")
    svc = _svc()
    f1 = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f1["id"])
    f2 = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f2["id"])
    outlook = svc.get_business_outlook(db_session, pid)
    assert outlook["forecast"]["id"] == f2["id"]  # последний


def test_business_outlook_empty_project(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc6")
    outlook = _svc().get_business_outlook(db_session, pid)
    assert outlook["forecast"] is None
    assert "baseline" in outlook


def test_explain_forecast_mentions_no_guarantee(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc7")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    exp = svc.explain_forecast(db_session, f["id"])
    assert any("гаранти" in r.lower() for r in exp["reasons"])


def test_summary_counts(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsvc8")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    summary = svc.get_summary(db_session, pid)
    assert summary["forecasts_total"] == 1
    assert summary["forecasts_generated"] == 1


def test_audit_entries_written(db_session: Session) -> None:
    """created/generated/metric_created/roadmap_created пишут forecast.* в AuditLog."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "fcsvc9")
    svc = _svc()
    f = svc.create_forecast(db_session, pid, user_id=uid)
    svc.generate_business_outlook(db_session, f["id"], user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "forecast.created",
        "forecast.generated",
        "forecast.metric_created",
        "forecast.roadmap_created",
    ):
        assert expected in actions


def test_missing_forecast_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIBusinessForecastingError, match="не найден"):
        _svc().get_forecast(db_session, 999999)


def test_missing_project_raises_not_found(db_session: Session) -> None:
    with pytest.raises(AIBusinessForecastingError, match="не найден"):
        _svc().create_forecast(db_session, 999999)
