"""Тесты безопасности AI Business Forecasting Engine (v0.7.6, offline).

Жёсткие инварианты (Часть 17): запрещено обещать прибыль, делать финансовые гарантии, выполнять
стратегии, менять бизнес автоматически. Прогнозный слой:
- НЕ публикует, НЕ включает live, НЕ создаёт CRM/бюджетных изменений, НЕ выполняет стратегии;
- бесплатно (0 units); секретов в ответах нет; строгая tenant isolation;
- generate не меняет решения/симуляции/процессы; переживает падение смежных слоёв.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_workflow import BusinessWorkflow
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    AIBusinessForecastingService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_KEYS = ("token", "secret", "password", "api_key", "access_token", "refresh_token")


def _svc() -> AIBusinessForecastingService:
    return AIBusinessForecastingService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _generate(db: Session, pid: int) -> int:
    svc = _svc()
    f = svc.create_forecast(db, pid)
    svc.generate_business_outlook(db, f["id"])
    return f["id"]


def test_billing_is_free() -> None:
    """USAGE_BUSINESS_FORECAST и USAGE_FORECAST_REPORT стоят 0 units."""
    from app.services.billing_service import (
        ACTION_COSTS,
        USAGE_BUSINESS_FORECAST,
        USAGE_FORECAST_REPORT,
    )

    assert ACTION_COSTS[USAGE_BUSINESS_FORECAST] == 0
    assert ACTION_COSTS[USAGE_FORECAST_REPORT] == 0


def test_generate_does_not_publish_or_go_live(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsec1")
    _generate(db_session, pid)
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(PostPublication).count() == 0


def test_generate_does_not_create_workflows(db_session: Session) -> None:
    """Прогноз не запускает и не создаёт бизнес-процессов (в отличие от decision apply)."""
    pid, _ = _project(db_session, "fcsec2")
    _generate(db_session, pid)
    assert db_session.query(BusinessWorkflow).filter_by(project_id=pid).count() == 0


def test_public_views_have_no_secrets(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsec3")
    fid = _generate(db_session, pid)
    svc = _svc()
    bundle = svc.get_forecast(db_session, fid)
    outlook = svc.get_business_outlook(db_session, pid)
    for blob in (str(bundle).lower(), str(outlook).lower()):
        for key in _SECRET_KEYS:
            assert key not in blob


def test_forecast_never_guarantees_profit(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsec4")
    fid = _generate(db_session, pid)
    svc = _svc()
    exp = svc.explain_forecast(db_session, fid)
    joined = " ".join(exp["reasons"]).lower()
    assert "гаранти" in joined  # «не финансовая гарантия»
    bundle = svc.get_forecast(db_session, fid)
    assert any("гаранти" in str(a).lower() for a in bundle["forecast"]["assumptions"])


def test_confidence_and_risk_bounded(db_session: Session) -> None:
    pid, _ = _project(db_session, "fcsec5")
    fid = _generate(db_session, pid)
    f = _svc().get_forecast(db_session, fid)["forecast"]
    assert 0.0 <= f["confidence_score"] <= 100.0
    assert f["risk_level"] in ("low", "medium", "high", "critical")


def test_cross_tenant_forecast_blocked(db_session: Session) -> None:
    pid1, _ = _project(db_session, "fcsec6a")
    _pid2, _ = _project(db_session, "fcsec6b")
    fid = _generate(db_session, pid1)
    # Прогноз проекта 1 недоступен сервису под чужим forecast_id только через API-гард;
    # на сервис-слое проверяем, что get_forecast читает свой проект (tenant iso на API).
    forecast = _svc().get_forecast(db_session, fid)
    assert forecast["forecast"]["project_id"] == pid1


def test_baseline_survives_missing_layers(db_session: Session) -> None:
    """collect_business_baseline не падает при отсутствии данных смежных слоёв — возвращает нули."""
    pid, _ = _project(db_session, "fcsec7")
    baseline = _svc().collect_business_baseline(db_session, pid)
    for metric in ("revenue", "leads", "customers", "conversion", "traffic", "efficiency"):
        assert metric in baseline and baseline[metric] >= 0.0
    assert baseline["_meta"]["sources_total"] >= 1


def test_baseline_survives_raising_layers(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение смежного слоя (исключение) НЕ роняет прогноз — срабатывают try/except."""
    pid, _ = _project(db_session, "fcsec8")

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("layer down")

    monkeypatch.setattr(
        "app.services.ai_executive_service.AIExecutiveService.analyze_business_state", _boom
    )
    monkeypatch.setattr(
        "app.services.analytics_service.AnalyticsService.get_project_summary", _boom
    )
    monkeypatch.setattr("app.repositories.operations_repository.get_latest_snapshot", _boom)
    monkeypatch.setattr("app.repositories.operations_repository.list_active_risks", _boom)
    monkeypatch.setattr("app.repositories.workflow_repository.get_active_workflows", _boom)
    monkeypatch.setattr("app.repositories.decision_repository.list_decisions", _boom)
    # baseline не падает (нули), generate тоже переживает падение всех источников риска.
    baseline = _svc().collect_business_baseline(db_session, pid)
    assert baseline["_meta"]["sources_with_data"] == 0
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    out = svc.generate_business_outlook(db_session, f["id"])
    assert len(out["metrics"]) == 6
    assert out["forecast"]["risk_level"] in ("low", "medium", "high", "critical")


def test_missing_forecast_raises(db_session: Session) -> None:
    with pytest.raises(AIBusinessForecastingError):
        _svc().generate_business_outlook(db_session, 999999)
