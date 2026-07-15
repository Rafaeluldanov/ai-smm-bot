"""Тесты бизнес-roadmap — AI Business Forecasting (v0.7.6, offline).

Инварианты:
- roadmap = 4 квартала (Q1–Q4) с целями; вехи по горизонтам; риски из поправки на риск;
- рекомендации по слабым метрикам; повторная генерация пересоздаёт (не размножает); только советы.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import business_forecast_repository as repo
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


def _generated(db: Session, slug: str) -> tuple[int, int]:
    pid, uid = _project(db, slug)
    svc = _svc()
    f = svc.create_forecast(db, pid)
    svc.generate_business_outlook(db, f["id"])
    return pid, f["id"]


def test_roadmap_has_four_quarters(db_session: Session) -> None:
    _pid, fid = _generated(db_session, "rm1")
    roadmap = _svc().get_roadmap(db_session, fid)
    assert roadmap is not None
    quarters = roadmap["quarters"]
    assert [q["quarter"] for q in quarters] == ["Q1", "Q2", "Q3", "Q4"]
    assert all(q["goals"] for q in quarters)


def test_roadmap_has_milestones_and_recommendations(db_session: Session) -> None:
    _pid, fid = _generated(db_session, "rm2")
    roadmap = _svc().get_roadmap(db_session, fid)
    assert roadmap["milestones"]
    assert roadmap["recommendations"]


def test_roadmap_risks_reflect_risk_signals(db_session: Session) -> None:
    _pid, fid = _generated(db_session, "rm3")
    roadmap = _svc().get_roadmap(db_session, fid)
    # Всегда есть строка про общий уровень риска.
    assert any("риск" in str(r).lower() for r in roadmap["risks"])


def test_regenerate_does_not_multiply_roadmap(db_session: Session) -> None:
    pid, uid = _project(db_session, "rm4")
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    svc.generate_business_outlook(db_session, f["id"])
    from sqlalchemy import func

    from app.models.business_roadmap import BusinessRoadmap

    count = db_session.query(func.count(BusinessRoadmap.id)).filter_by(forecast_id=f["id"]).scalar()
    assert count == 1


def test_roadmap_empty_project_recommends_data_setup(db_session: Session) -> None:
    """На пустом проекте рекомендации советуют наладить измерение (без выручки/лидов)."""
    _pid, fid = _generated(db_session, "rm5")
    roadmap = _svc().get_roadmap(db_session, fid)
    joined = " ".join(str(r) for r in roadmap["recommendations"]).lower()
    assert "конвер" in joined or "лид" in joined or "продаж" in joined or "импульс" in joined


def test_roadmap_view_shape(db_session: Session) -> None:
    _pid, fid = _generated(db_session, "rm6")
    roadmap = repo.get_roadmap(db_session, fid)
    view = repo.public_roadmap_view(roadmap)
    for key in ("id", "forecast_id", "title", "quarters", "milestones", "risks", "recommendations"):
        assert key in view


def test_real_risk_signals_escalate_risk(db_session: Session) -> None:
    """Реальные риск-сигналы (Operations/Workflow/Decision) повышают штраф, уровень и risks roadmap.

    Ловит регрессию сигнатур смежных слоёв: list_active_risks / get_active_workflows /
    list_blockers(status) / list_decisions / list_scenarios(risk_analysis['risk']).
    """
    from app.repositories import decision_repository as drepo
    from app.repositories import operations_repository as ops_repo
    from app.repositories import workflow_repository as wf_repo

    pid, uid = _project(db_session, "rm7")
    acc = None
    # (1) Открытый операционный риск + снапшот с низким health (< 70).
    ops_repo.create_risk(
        db_session,
        project_id=pid,
        account_id=acc,
        risk_type="revenue_drop",
        title="Падение выручки",
        severity="high",
    )
    ops_repo.create_snapshot(
        db_session, project_id=pid, account_id=acc, health_score=45.0, status="warning"
    )
    # (2) Активный процесс с открытым блокером.
    wf = wf_repo.create_workflow(
        db_session,
        project_id=pid,
        account_id=acc,
        name="Процесс",
        workflow_type="growth",
        status="active",
    )
    wf_repo.create_blocker(db_session, workflow_id=wf.id, blocker_type="dependency", title="Блокер")
    # (3) Решение со сценарием повышенного риска (>= 60).
    decision = drepo.create_decision(
        db_session, project_id=pid, account_id=acc, decision_type="growth", title="Решение"
    )
    drepo.create_scenario(
        db_session, decision_id=decision.id, title="Рискованный", risk_analysis={"risk": 75}
    )

    risk = _svc().apply_risk_adjustment(db_session, pid)
    assert risk["risk_penalty"] > 0
    assert risk["risk_level"] in ("medium", "high", "critical")
    signals = risk["signals"]
    assert signals["operations_risks"] >= 1
    assert signals["workflow_blockers"] >= 1
    assert signals["decision_risks"] >= 1
    assert signals["health_score"] < 70

    # roadmap отражает эти риск-сигналы (не только дефолтную строку уровня).
    svc = _svc()
    f = svc.create_forecast(db_session, pid)
    svc.generate_business_outlook(db_session, f["id"])
    roadmap = svc.get_roadmap(db_session, f["id"])
    joined = " ".join(str(r) for r in roadmap["risks"]).lower()
    assert "операц" in joined and "блокер" in joined
