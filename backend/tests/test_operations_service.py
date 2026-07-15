"""Тесты AIOperationsControlService — AI Operations Control Center (v0.7.3, offline).

Инварианты:
- snapshot создаётся; health считается; risks детектятся (дедуп); recommendations создаются;
- resolve/accept/reject только меняют статус (НЕ выполняют действий, no live/CRM);
- tenant isolation; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.ai_operations_control_service import (
    AIOperationsControlError,
    AIOperationsControlService,
)
from app.services.ai_workflow_manager_service import AIWorkflowManagerService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOperationsControlService:
    return AIOperationsControlService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _blocked_workflow(db: Session, pid: int) -> None:
    """Активный процесс с блокером → триггерит execution_block risk."""
    wf = AIWorkflowManagerService(settings=_SETTINGS)
    wid = wf.create_workflow_from_goal(db, pid, name="P", workflow_type="sales", status="active")[
        "id"
    ]
    step = wf.generate_workflow_steps(db, wid)[0]["id"]
    wf.create_blocker(db, wid, blocker_type="approval", title="Ждём", step_id=step)


def test_snapshot_created(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc1")
    out = _svc().build_operations_snapshot(db_session, pid, user_id=uid)
    snap = out["snapshot"]
    assert 0 <= snap["health_score"] <= 100
    assert snap["status"] in ("healthy", "warning", "critical")
    assert "growth" in snap["metrics"] and "risk_penalty" in snap["metrics"]


def test_health_score_bounds_and_penalty() -> None:
    svc = _svc()
    comp = {"growth": 80.0, "revenue": 75.0, "execution": 70.0, "workflow_progress": 80.0}
    high = svc.calculate_health_score(comp, 0.0)
    low = svc.calculate_health_score(comp, 40.0)
    assert 0 <= low <= high <= 100
    assert high > low  # штраф снижает health


def test_risks_detected_and_deduped(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc2")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    out = svc.build_operations_snapshot(db_session, pid, user_id=uid)
    types = {r["risk_type"] for r in out["risks"]}
    assert "execution_block" in types  # из открытого блокера процесса
    before = len(svc.list_active_risks(db_session, pid))
    svc.build_operations_snapshot(db_session, pid, user_id=uid)
    # повторный анализ не плодит дубликаты открытых рисков того же типа
    assert len(svc.list_active_risks(db_session, pid)) == before


def test_recommendations_created_from_risks(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc3")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    out = svc.build_operations_snapshot(db_session, pid, user_id=uid)
    assert out["recommendations"], "из рисков должны появиться рекомендации"
    # повторный анализ не дублирует рекомендации по заголовку
    out2 = svc.build_operations_snapshot(db_session, pid, user_id=uid)
    assert out2["recommendations"] == []


def test_resolve_risk_no_external_actions(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc4")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    risk_id = svc.build_operations_snapshot(db_session, pid, user_id=uid)["risks"][0]["id"]
    r = svc.resolve_risk(db_session, risk_id, user_id=uid)
    assert r["status"] == "resolved" and r["resolved_at"] is not None
    with pytest.raises(AIOperationsControlError):  # double resolve
        svc.resolve_risk(db_session, risk_id)
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0


def test_accept_reject_recommendation(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc5")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    svc.build_operations_snapshot(db_session, pid, user_id=uid)
    recs = svc.list_recommendations(db_session, pid, status="generated")
    assert recs
    acc = svc.accept_recommendation(db_session, recs[0]["id"], user_id=uid)
    assert acc["status"] == "accepted"
    with pytest.raises(AIOperationsControlError):  # уже обработана
        svc.accept_recommendation(db_session, recs[0]["id"])
    if len(recs) > 1:
        rej = svc.reject_recommendation(db_session, recs[1]["id"], user_id=uid)
        assert rej["status"] == "rejected"


def test_explain_and_history_and_summary(db_session: Session) -> None:
    pid, uid = _project(db_session, "opssvc6")
    svc = _svc()
    svc.build_operations_snapshot(db_session, pid, user_id=uid)
    assert svc.explain_operations_state(db_session, pid)["reasons"]
    assert len(svc.get_history(db_session, pid)) == 1
    got = svc.get_operations(db_session, pid)
    assert got["has_snapshot"] is True
    summary = svc.get_summary(db_session, pid)
    assert summary["has_snapshot"] is True


def test_recommendations_not_resurrected_after_accept_reject(db_session: Session) -> None:
    """Принятые/отклонённые рекомендации не появляются заново при повторном анализе."""
    pid, uid = _project(db_session, "opssvc7")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    recs = svc.build_operations_snapshot(db_session, pid, user_id=uid)["recommendations"]
    assert recs
    svc.accept_recommendation(db_session, recs[0]["id"], user_id=uid)
    if len(recs) > 1:
        svc.reject_recommendation(db_session, recs[1]["id"], user_id=uid)
    keys = {r["title"] for r in recs}
    svc.build_operations_snapshot(db_session, pid, user_id=uid)
    all_titles = [r["title"] for r in svc.list_recommendations(db_session, pid)]
    # каждый обработанный заголовок остаётся в единственном экземпляре (не воскрешён)
    for title in keys:
        assert all_titles.count(title) == 1


def test_revenue_and_conversion_drop_detected(db_session: Session) -> None:
    """Снижение выручки/конверсии между снапшотами → risks revenue_drop/conversion_drop."""
    from app.repositories import operations_repository as ops_repo

    pid, uid = _project(db_session, "opssvc8")
    svc = _svc()
    svc.build_operations_snapshot(db_session, pid, user_id=uid)  # снапшот 1
    snap1 = ops_repo.get_latest_snapshot(db_session, pid)
    snap1.sales_state = {"revenue": 999999.0, "conversion": 0.9, "leads": 10}
    db_session.commit()
    svc.build_operations_snapshot(db_session, pid, user_id=uid)  # снапшот 2 читает 1 как prev
    types = {r["risk_type"] for r in svc.list_active_risks(db_session, pid)}
    assert "revenue_drop" in types and "conversion_drop" in types


def test_reject_and_accept_terminal_guards(db_session: Session) -> None:
    """accept/reject возможны только из generated; повторная обработка запрещена."""
    pid, uid = _project(db_session, "opssvc9")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    recs = svc.build_operations_snapshot(db_session, pid, user_id=uid)["recommendations"]
    assert recs
    rid = recs[0]["id"]
    svc.reject_recommendation(db_session, rid, user_id=uid)
    with pytest.raises(AIOperationsControlError):  # double reject
        svc.reject_recommendation(db_session, rid)
    with pytest.raises(AIOperationsControlError):  # accept после reject
        svc.accept_recommendation(db_session, rid)


def test_no_snapshot_state(db_session: Session) -> None:
    """До анализа: get_operations пуст, explain просит запустить анализ."""
    pid, _uid = _project(db_session, "opssvc10")
    svc = _svc()
    got = svc.get_operations(db_session, pid)
    assert got["has_snapshot"] is False and got["snapshot"] is None
    reasons = svc.explain_operations_state(db_session, pid)["reasons"]
    assert reasons and "анализ" in reasons[0].lower()


def test_audit_entries_written(db_session: Session) -> None:
    """snapshot/risk/recommendation изменения пишут operations.* в AuditLog."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "opssvc11")
    _blocked_workflow(db_session, pid)
    svc = _svc()
    out = svc.build_operations_snapshot(db_session, pid, user_id=uid)
    svc.resolve_risk(db_session, out["risks"][0]["id"], user_id=uid)
    recs = svc.list_recommendations(db_session, pid, status="generated")
    svc.accept_recommendation(db_session, recs[0]["id"], user_id=uid)
    if len(recs) > 1:
        svc.reject_recommendation(db_session, recs[1]["id"], user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "operations.snapshot_created",
        "operations.risk_created",
        "operations.risk_resolved",
        "operations.recommendation_created",
        "operations.recommendation_accepted",
    ):
        assert expected in actions


def test_missing_project_raises(db_session: Session) -> None:
    with pytest.raises(AIOperationsControlError):
        _svc().build_operations_snapshot(db_session, 999999)
