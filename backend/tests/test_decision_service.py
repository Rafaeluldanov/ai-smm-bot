"""Тесты AIDecisionEngineService — AI Decision Engine (v0.7.4, offline).

Инварианты:
- decision создаётся; signals собираются; scenarios строятся; лучший рекомендуется;
- accept обязателен, apply требует APPLY_DECISION → лишь draft workflow (no live/CRM/бюджет);
- tenant isolation; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.business_workflow import BusinessWorkflow
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_decision_engine_service import (
    APPLY_CONFIRMATION,
    AIDecisionEngineError,
    AIDecisionEngineService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIDecisionEngineService:
    return AIDecisionEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _decision(db: Session, pid: int, dtype: str = "efficiency") -> int:
    return _svc().create_decision(
        db,
        pid,
        decision_type=dtype,
        title="Низкая конверсия",
        problem_statement="Много просмотров, мало заявок",
    )["id"]


def test_create_decision(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc1")
    d = _svc().create_decision(db_session, pid, decision_type="growth", title="Рост", user_id=uid)
    assert d["status"] == "draft" and d["decision_type"] == "growth"


def test_create_rejects_unknown_type(db_session: Session) -> None:
    pid, _ = _project(db_session, "decsvc1b")
    with pytest.raises(AIDecisionEngineError):
        _svc().create_decision(db_session, pid, decision_type="bogus", title="x")


def test_analyze_generates_scenarios_and_recommendation(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc2")
    svc = _svc()
    did = _decision(db_session, pid)
    out = svc.analyze_decision(db_session, did, user_id=uid)
    assert out["decision"]["status"] == "recommended"
    assert len(out["scenarios"]) == 3
    for s in out["scenarios"]:
        assert "score" in s["expected_impact"]  # оценён
    rec = out["recommendation"]
    assert rec["scenario"] is not None and 0 <= rec["score"] <= 100
    assert out["decision"]["recommended_scenario_id"] == rec["scenario"]["id"]


def test_signals_collected(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc3")
    svc = _svc()
    did = _decision(db_session, pid)
    svc.analyze_decision(db_session, did, user_id=uid)
    signals = svc.get_decision(db_session, did)["signals"]
    sources = {s["source_module"] for s in signals}
    assert {"growth_agent", "sales_intelligence", "workflow_manager"} <= sources


def test_reanalyze_dedups_scenarios_and_signals(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc4")
    svc = _svc()
    did = _decision(db_session, pid)
    svc.analyze_decision(db_session, did, user_id=uid)
    bundle = svc.get_decision(db_session, did)
    n_sc, n_sig = len(bundle["scenarios"]), len(bundle["signals"])
    svc.analyze_decision(db_session, did, user_id=uid)
    bundle2 = svc.get_decision(db_session, did)
    assert len(bundle2["scenarios"]) == n_sc and len(bundle2["signals"]) == n_sig


def test_best_scenario_is_max_score(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc5")
    svc = _svc()
    did = _decision(db_session, pid)
    out = svc.analyze_decision(db_session, did, user_id=uid)
    scores = [s["expected_impact"]["score"] for s in out["scenarios"] if s["status"] != "rejected"]
    assert out["recommendation"]["score"] == max(scores)


def test_apply_requires_accept_and_confirmation(db_session: Session) -> None:
    pid, uid = _project(db_session, "decsvc6")
    svc = _svc()
    did = _decision(db_session, pid)
    svc.analyze_decision(db_session, did, user_id=uid)
    with pytest.raises(AIDecisionEngineError):  # ещё не accepted
        svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION)
    svc.accept_decision(db_session, did, user_id=uid)
    with pytest.raises(AIDecisionEngineError):  # нет подтверждения
        svc.apply_decision(db_session, did, confirmation="")
    res = svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION, user_id=uid)
    assert res["live_enabled"] is False
    assert res["decision"]["status"] == "applied"
    # apply создал ЧЕРНОВИК процесса (status=draft), не запустил его
    workflows = db_session.query(BusinessWorkflow).filter_by(project_id=pid).all()
    assert len(workflows) == 1 and workflows[0].status == "draft"
    # никаких публикаций/live
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_accept_before_analyze_blocked(db_session: Session) -> None:
    pid, _ = _project(db_session, "decsvc7")
    did = _decision(db_session, pid)
    with pytest.raises(AIDecisionEngineError):  # ещё не проанализировано (draft)
        _svc().accept_decision(db_session, did)


def test_apply_draft_workflow_type_mapping(db_session: Session) -> None:
    """apply создаёт draft workflow с типом по типу решения (efficiency→operational)."""
    from app.models.business_workflow import BusinessWorkflow

    svc = _svc()

    def apply_type(slug: str, dtype: str) -> str:
        pid, uid = _project(db_session, slug)
        did = svc.create_decision(db_session, pid, decision_type=dtype, title="P")["id"]
        svc.analyze_decision(db_session, did)
        svc.accept_decision(db_session, did)
        svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION)
        wf = db_session.query(BusinessWorkflow).filter_by(project_id=pid).one()
        assert wf.status == "draft"
        return wf.workflow_type

    assert apply_type("decwf1", "efficiency") == "operational"
    assert apply_type("decwf2", "growth") == "growth"


def test_audit_entries_written(db_session: Session) -> None:
    """create/analyze/scenario/accept/apply пишут decision.* в AuditLog (project-scoped)."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "decsvc8")
    svc = _svc()
    out = svc.create_decision(db_session, pid, decision_type="sales", title="P", user_id=uid)
    did = out["id"]
    scenarios = svc.analyze_decision(db_session, did, user_id=uid)["scenarios"]
    svc.select_scenario(db_session, scenarios[0]["id"], user_id=uid)
    svc.reject_scenario(db_session, scenarios[1]["id"], user_id=uid)
    svc.accept_decision(db_session, did, user_id=uid)
    svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "decision.created",
        "decision.analyzed",
        "decision.scenario_created",
        "decision.scenario_selected",
        "decision.scenario_rejected",
        "decision.accepted",
        "decision.applied",
    ):
        assert expected in actions


def test_reanalyze_blocked_after_apply(db_session: Session) -> None:
    """analyze запрещён на applied-решении; статус остаётся applied."""
    from app.repositories import decision_repository as drepo

    pid, uid = _project(db_session, "decsvc9")
    svc = _svc()
    did = _decision(db_session, pid)
    svc.analyze_decision(db_session, did)
    svc.accept_decision(db_session, did)
    svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION)
    with pytest.raises(AIDecisionEngineError):
        svc.analyze_decision(db_session, did)
    assert drepo.get_decision(db_session, did).status == "applied"


def test_apply_ignores_rejected_recommended_scenario(db_session: Session) -> None:
    """Если рекомендованный сценарий отклонён после accept, apply не строит из него черновик."""
    from app.models.business_workflow import BusinessWorkflow
    from app.repositories import decision_repository as drepo

    pid, uid = _project(db_session, "decsvc10")
    svc = _svc()
    did = _decision(db_session, pid)
    rec_id = svc.analyze_decision(db_session, did)["decision"]["recommended_scenario_id"]
    svc.accept_decision(db_session, did)
    rec_title = drepo.get_scenario(db_session, rec_id).title
    svc.reject_scenario(db_session, rec_id)  # reject после accept → не переуказывает
    svc.apply_decision(db_session, did, confirmation=APPLY_CONFIRMATION)
    wf = db_session.query(BusinessWorkflow).filter_by(project_id=pid).one()
    assert wf.name != rec_title  # черновик НЕ из отклонённого сценария


def test_missing_decision_raises(db_session: Session) -> None:
    with pytest.raises(AIDecisionEngineError):
        _svc().get_decision(db_session, 999999)
