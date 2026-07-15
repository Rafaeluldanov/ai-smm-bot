"""Тесты AIChiefOfStaffService — AI Chief of Staff (v0.7.1, offline).

Инварианты:
- briefing (daily/weekly) создаётся; weekly сравнивает окна; задачи создаются (дедуп);
- accept/complete/reject только меняют статус (НЕ выполняют действия, no live/CRM);
- decision memory сохраняется и влияет на контекст; tenant isolation; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.ai_lead_event import AILeadEvent
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_chief_of_staff_service import (
    AIChiefOfStaffError,
    AIChiefOfStaffService,
)
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIChiefOfStaffService:
    return AIChiefOfStaffService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _seed_revenue(db: Session, project_id: int, value: float = 70000) -> None:
    from app.repositories import post_repository

    post = post_repository.create_post(
        db, PostCreate(project_id=project_id, title="Кейс", status="published", vk_text="x")
    )
    AISalesIntelligenceService(settings=_SETTINGS).record_lead_event(
        db, project_id, event_type="deal_won", post_id=post.id, platform_key="telegram", value=value
    )


def test_daily_briefing_created(db_session: Session) -> None:
    pid = _project(db_session, "chsvc1")
    _seed_revenue(db_session, pid)
    out = _svc().generate_daily_briefing(db_session, pid)
    b = out["briefing"]
    assert b["type"] == "daily" and b["status"] == "generated"
    assert b["summary"]
    assert b["key_changes"]
    assert out["tasks"], "из приоритетных действий должны появиться задачи"


def test_weekly_review_compares_windows(db_session: Session) -> None:
    pid = _project(db_session, "chsvc2")
    _seed_revenue(db_session, pid)
    out = _svc().generate_weekly_review(db_session, pid)
    b = out["briefing"]
    assert b["type"] == "weekly"
    state = b["business_state"]
    assert "this_week" in state and "prev_week" in state
    assert state["this_week"]["revenue"] >= 0


def test_tasks_created_with_priority_and_dedup(db_session: Session) -> None:
    pid = _project(db_session, "chsvc3")
    _seed_revenue(db_session, pid)
    svc = _svc()
    first = svc.generate_daily_briefing(db_session, pid)["tasks"]
    assert first
    for t in first:
        assert t["priority"] in ("critical", "high", "medium", "low")
    total = len(svc.list_tasks(db_session, pid))
    # повторный брифинг не плодит дубли задач
    svc.generate_daily_briefing(db_session, pid)
    assert len(svc.list_tasks(db_session, pid)) == total


def test_accept_complete_flow_no_external_actions(db_session: Session) -> None:
    pid = _project(db_session, "chsvc4")
    _seed_revenue(db_session, pid)
    svc = _svc()
    task_id = svc.generate_daily_briefing(db_session, pid)["tasks"][0]["id"]
    leads_before = db_session.query(AILeadEvent).count()
    acc = svc.accept_task(db_session, task_id)
    assert acc["status"] == "accepted"
    comp = svc.complete_task(db_session, task_id)
    assert comp["status"] == "completed" and comp["completed_at"] is not None
    # никаких внешних действий: ни публикаций, ни новых CRM-событий
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(AILeadEvent).count() == leads_before


def test_reject_task(db_session: Session) -> None:
    pid = _project(db_session, "chsvc5")
    _seed_revenue(db_session, pid)
    svc = _svc()
    task_id = svc.generate_daily_briefing(db_session, pid)["tasks"][0]["id"]
    rej = svc.reject_task(db_session, task_id)
    assert rej["status"] == "rejected"
    with pytest.raises(AIChiefOfStaffError):  # нельзя завершить отклонённую
        svc.complete_task(db_session, task_id)


def test_completed_task_cannot_be_reaccepted(db_session: Session) -> None:
    pid = _project(db_session, "chsvc6")
    _seed_revenue(db_session, pid)
    svc = _svc()
    task_id = svc.generate_daily_briefing(db_session, pid)["tasks"][0]["id"]
    svc.accept_task(db_session, task_id)
    svc.complete_task(db_session, task_id)
    with pytest.raises(AIChiefOfStaffError):
        svc.accept_task(db_session, task_id)


def test_briefing_viewed(db_session: Session) -> None:
    pid = _project(db_session, "chsvc7")
    _seed_revenue(db_session, pid)
    svc = _svc()
    bid = svc.generate_daily_briefing(db_session, pid)["briefing"]["id"]
    viewed = svc.mark_briefing_viewed(db_session, bid)
    assert viewed["status"] == "viewed" and viewed["viewed_at"] is not None
    got = svc.get_latest_briefing(db_session, pid)
    assert got["has_briefing"] is True and got["briefing"]["id"] == bid


def test_rebriefing_keeps_open_tasks_attached(db_session: Session) -> None:
    """Повторный брифинг (все действия задедуплены) не должен оставить брифинг без задач."""
    pid = _project(db_session, "chsvc8")
    _seed_revenue(db_session, pid)
    svc = _svc()
    first = svc.generate_daily_briefing(db_session, pid)["tasks"]
    assert first
    out2 = svc.generate_daily_briefing(db_session, pid)
    assert out2["tasks"], "повторный брифинг должен показывать открытые задачи"
    got = svc.get_latest_briefing(db_session, pid)
    assert len(got["tasks"]) == len(out2["tasks"])
    # терминальные (rejected) задачи не переезжают в новейший брифинг
    from app.repositories import chief_of_staff_repository as repo

    svc.reject_task(db_session, first[0]["id"])
    out3 = svc.generate_daily_briefing(db_session, pid)
    b3_id = out3["briefing"]["id"]
    assert repo.get_task(db_session, first[0]["id"]).briefing_id != b3_id
    assert all(t["id"] != first[0]["id"] for t in out3["tasks"])


def test_weekly_review_declining_windows(db_session: Session) -> None:
    """Weekly с данными в ОБОИХ окнах: падение → корректные дельты и weekly-риски."""
    from datetime import UTC, datetime, timedelta

    pid = _project(db_session, "chsvcw")
    now = datetime.now(UTC)
    sales = AISalesIntelligenceService(settings=_SETTINGS)
    sales.record_lead_event(db_session, pid, event_type="deal_won", value=100000)
    prev = db_session.query(AILeadEvent).order_by(AILeadEvent.id.desc()).first()
    assert prev is not None
    prev.created_at = now - timedelta(days=10)  # предыдущая неделя
    db_session.commit()
    sales.record_lead_event(db_session, pid, event_type="deal_won", value=70000)  # эта неделя
    out = _svc().generate_weekly_review(db_session, pid)
    state = out["briefing"]["business_state"]
    assert state["prev_week"]["revenue"] == 100000
    assert state["this_week"]["revenue"] == 70000
    assert any("сниз" in c.lower() for c in out["briefing"]["key_changes"])
    assert "Выручка за неделю снизилась" in out["briefing"]["risks"]


def test_dedup_across_terminal_statuses(db_session: Session) -> None:
    """Дедуп задач держится и для терминальных (completed/rejected)."""
    pid = _project(db_session, "chsvc10")
    _seed_revenue(db_session, pid)
    svc = _svc()
    tasks = svc.generate_daily_briefing(db_session, pid)["tasks"]
    assert len(tasks) >= 2
    svc.reject_task(db_session, tasks[0]["id"])
    svc.accept_task(db_session, tasks[1]["id"])
    svc.complete_task(db_session, tasks[1]["id"])
    svc.generate_daily_briefing(db_session, pid)
    seen = [(t["task_type"], t["title"]) for t in svc.list_tasks(db_session, pid)]
    assert len(seen) == len(set(seen))


def test_terminal_transitions_blocked(db_session: Session) -> None:
    """Терминальные статусы задачи неизменны: double-complete, double-reject, cross-terminal."""
    pid = _project(db_session, "chsvc11")
    _seed_revenue(db_session, pid)
    svc = _svc()
    tasks = svc.generate_daily_briefing(db_session, pid)["tasks"]
    a, b = tasks[0]["id"], tasks[1]["id"]
    svc.reject_task(db_session, a)
    with pytest.raises(AIChiefOfStaffError):  # accept после reject
        svc.accept_task(db_session, a)
    with pytest.raises(AIChiefOfStaffError):  # double reject
        svc.reject_task(db_session, a)
    svc.accept_task(db_session, b)
    with pytest.raises(AIChiefOfStaffError):  # double accept (no-op, без дубля аудита)
        svc.accept_task(db_session, b)
    svc.complete_task(db_session, b)
    with pytest.raises(AIChiefOfStaffError):  # double complete
        svc.complete_task(db_session, b)
    with pytest.raises(AIChiefOfStaffError):  # reject после complete
        svc.reject_task(db_session, b)


def test_accepted_task_reassigned_completed_excluded(db_session: Session) -> None:
    """Повторный брифинг: открытая accepted-задача переезжает в новый брифинг, completed — нет."""
    from app.repositories import chief_of_staff_repository as repo

    pid = _project(db_session, "chsvc13")
    _seed_revenue(db_session, pid)
    svc = _svc()
    tasks = svc.generate_daily_briefing(db_session, pid)["tasks"]
    assert len(tasks) >= 2
    svc.accept_task(db_session, tasks[0]["id"])  # открытая accepted
    svc.accept_task(db_session, tasks[1]["id"])
    svc.complete_task(db_session, tasks[1]["id"])  # терминальная
    b2 = svc.generate_daily_briefing(db_session, pid)["briefing"]["id"]
    assert repo.get_task(db_session, tasks[0]["id"]).briefing_id == b2
    assert repo.get_task(db_session, tasks[1]["id"]).briefing_id != b2
    latest_ids = {t["id"] for t in svc.get_latest_briefing(db_session, pid)["tasks"]}
    assert tasks[0]["id"] in latest_ids and tasks[1]["id"] not in latest_ids


def test_audit_entries_written(db_session: Session) -> None:
    """analyze/task/decision пишут события chief.* в AuditLog (project-scoped)."""
    from app.models.audit_log import AuditLogEntry

    pid = _project(db_session, "chsvc12")
    _seed_revenue(db_session, pid)
    svc = _svc()
    tid = svc.generate_daily_briefing(db_session, pid)["tasks"][0]["id"]
    svc.accept_task(db_session, tid)
    svc.complete_task(db_session, tid)
    d = svc.save_decision_memory(db_session, pid, decision_type="preference", key="k", value={})
    svc.disable_decision(db_session, d["id"])
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    for expected in (
        "chief.briefing_generated",
        "chief.task_created",
        "chief.task_accepted",
        "chief.task_completed",
        "chief.memory_created",
        "chief.memory_deleted",
    ):
        assert expected in actions


def test_missing_project_raises(db_session: Session) -> None:
    with pytest.raises(AIChiefOfStaffError):
        _svc().generate_daily_briefing(db_session, 999999)
