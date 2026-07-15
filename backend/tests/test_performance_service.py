"""Тесты AIPerformanceIntelligenceService — score/отклонения/причины/рекомендации (v0.7.9, offline).

Инварианты:
- create_snapshot строит метрики + отклонения + рекомендации; score считается по формуле;
- deviations только для warning/critical; recommendations из отклонений; explain; аудит.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_business_planner_service import AIBusinessPlannerService
from app.services.ai_performance_intelligence_service import AIPerformanceIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIPerformanceIntelligenceService:
    return AIPerformanceIntelligenceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _below(db: Session, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    AIBusinessPlannerService(settings=_SETTINGS).create_business_goal(
        db, pid, goal_type="revenue", title="rev", target_value=1000000, current_value=100000
    )
    monkeypatch.setattr(
        "app.repositories.business_growth_repository.get_profile",
        lambda *_a, **_k: SimpleNamespace(
            current_state={"total_revenue": 700000.0, "conversion_rate": 0.1, "leads": 50},
            growth_score=40.0,
        ),
    )


def _above(db: Session, pid: int, monkeypatch: pytest.MonkeyPatch) -> None:
    AIBusinessPlannerService(settings=_SETTINGS).create_business_goal(
        db, pid, goal_type="revenue", title="rev", target_value=500000, current_value=100000
    )
    monkeypatch.setattr(
        "app.repositories.business_growth_repository.get_profile",
        lambda *_a, **_k: SimpleNamespace(
            current_state={"total_revenue": 600000.0, "conversion_rate": 0.3, "leads": 500},
            growth_score=95.0,
        ),
    )


def test_create_snapshot_full(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, uid = _project(db_session, "pfsvc1")
    _below(db_session, pid, monkeypatch)
    out = _svc().create_snapshot(db_session, pid, user_id=uid)
    assert out["metrics"]  # метрики созданы
    assert out["deviations"]  # revenue ниже плана → отклонение
    assert out["recommendations"]  # рекомендации созданы
    rev = [m for m in out["metrics"] if m["metric"] == "revenue"][0]
    assert rev["difference_percent"] == -30.0 and rev["status"] == "critical"


def test_deviation_only_for_underperformance(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Здоровые метрики не порождают отклонений (revenue выше плана → нет revenue-отклонения)."""
    pid, _ = _project(db_session, "pfsvc2")
    _above(db_session, pid, monkeypatch)
    out = _svc().create_snapshot(db_session, pid)
    dev_metrics = {d["metric"] for d in out["deviations"]}
    assert "revenue" not in dev_metrics  # 600k > 500k план → healthy


def test_score_bounded_and_deterministic(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid, _ = _project(db_session, "pfsvc3")
    _below(db_session, pid, monkeypatch)
    svc = _svc()
    s1 = svc.create_snapshot(db_session, pid)["snapshot"]["performance_score"]
    s2 = svc.create_snapshot(db_session, pid)["snapshot"]["performance_score"]
    assert 0.0 <= s1 <= 100.0 and s1 == s2  # детерминирован


def test_score_formula_components(db_session: Session) -> None:
    """kpi_score = avg(min(1, actual/target)) × 40; execution_score = progress/100 × 40."""
    pid, _ = _project(db_session, "pfsvc3b")  # без плана исполнения/рисков → velocity/risk = 0
    svc = _svc()
    comparison = [
        {"metric": "revenue", "target_value": 100.0, "actual_value": 50.0},
        {"metric": "leads", "target_value": 100.0, "actual_value": 100.0},
    ]
    # execution actual=100 → execution_score=40; kpi ratios (0.5,1.0) avg=0.75 → 30 → score=70.0
    score = svc.calculate_performance_score(db_session, pid, {"execution": 100.0}, comparison)
    assert score == 70.0


def test_explain_mentions_no_change(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    pid, _ = _project(db_session, "pfsvc4")
    _below(db_session, pid, monkeypatch)
    svc = _svc()
    snap = svc.create_snapshot(db_session, pid)["snapshot"]
    exp = svc.explain_performance(db_session, snap["id"])
    joined = " ".join(exp["reasons"]).lower()
    assert "score" in joined and "не меняются" in joined


def test_health_fallback_from_operations(db_session: Session) -> None:
    """Без профиля роста efficiency берётся из operations health_score (read-only fallback)."""
    from app.repositories import operations_repository as ops_repo

    pid, _ = _project(db_session, "pfsvc6")
    ops_repo.create_snapshot(
        db_session, project_id=pid, account_id=None, health_score=80.0, status="healthy"
    )
    actual = _svc().collect_actual_metrics(db_session, pid, None)
    assert actual["efficiency"] == 80.0  # из operations health_score


def test_risk_penalty_lowers_score(db_session: Session) -> None:
    """Открытый операционный риск повышает risk_penalty и снижает score (при положительной базе)."""
    from app.repositories import operations_repository as ops_repo

    pid, _ = _project(db_session, "pfsvc7")
    svc = _svc()
    # положительная база: execution=100 → execution_score=40; KPI revenue выполнен → kpi_score>0.
    actual = {"execution": 100.0}
    comparison = [{"metric": "revenue", "target_value": 100.0, "actual_value": 100.0}]
    score_before = svc.calculate_performance_score(db_session, pid, actual, comparison)
    assert score_before > 4.0  # база выше штрафа
    ops_repo.create_risk(
        db_session,
        project_id=pid,
        account_id=None,
        risk_type="revenue_drop",
        title="Падение",
        severity="high",
    )
    score_after = svc.calculate_performance_score(db_session, pid, actual, comparison)
    assert score_after == round(score_before - 4.0, 1)  # риск (×4) наказал score
    assert svc._risk_penalty(db_session, pid) >= 4.0


def test_audit_lifecycle(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "pfsvc5")
    _below(db_session, pid, monkeypatch)
    _svc().create_snapshot(db_session, pid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "performance.snapshot_created",
        "performance.metric_created",
        "performance.deviation_detected",
        "performance.recommendation_created",
    ):
        assert expected in actions
