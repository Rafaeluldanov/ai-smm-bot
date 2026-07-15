"""Тесты AIExecutiveService — Autonomous Business OS / AI Executive Layer (v0.7.0, offline).

Инварианты:
- анализ состояния собирается из всех слоёв; план + приоритизированные действия создаются;
- accept + APPLY_BUSINESS_ACTION обязательны; apply меняет лишь draft-стратегию/кампанию;
- apply НЕ включает live, НЕ публикует, НЕ создаёт CRM-лиды; dedup действий; секретов нет.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.ai_lead_event import AILeadEvent
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_executive_service import (
    APPLY_CONFIRMATION,
    AIExecutiveError,
    AIExecutiveService,
)
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIExecutiveService:
    return AIExecutiveService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _seed_revenue(db: Session, project_id: int, value: float = 50000) -> None:
    from app.repositories import post_repository

    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id, title="Кейс производства", status="published", vk_text="x"
        ),
    )
    AISalesIntelligenceService(settings=_SETTINGS).record_lead_event(
        db, project_id, event_type="deal_won", post_id=post.id, platform_key="telegram", value=value
    )


def test_analyze_business_state_keys(db_session: Session) -> None:
    pid = _project(db_session, "exsvc1")
    _seed_revenue(db_session, pid)
    state = _svc().analyze_business_state(db_session, pid)
    for key in (
        "business_health",
        "growth_score",
        "revenue_state",
        "content_state",
        "sales_state",
        "risks",
        "opportunities",
    ):
        assert key in state
    assert state["revenue_state"]["total_revenue"] == 50000


def test_create_and_list_objectives(db_session: Session) -> None:
    pid = _project(db_session, "exsvc2")
    obj = _svc().create_objective(db_session, pid, type="revenue_growth", title="Вырасти x2")
    assert obj["status"] == "draft" and obj["type"] == "revenue_growth"
    objs = _svc().list_objectives(db_session, pid)
    assert len(objs) == 1 and objs[0]["id"] == obj["id"]


def test_create_objective_rejects_unknown_type(db_session: Session) -> None:
    pid = _project(db_session, "exsvc2b")
    with pytest.raises(AIExecutiveError):
        _svc().create_objective(db_session, pid, type="not_a_type", title="x")


def test_executive_plan_creates_actions(db_session: Session) -> None:
    pid = _project(db_session, "exsvc3")
    _seed_revenue(db_session, pid)
    out = _svc().create_executive_plan(db_session, pid)
    assert out["plan"]["id"] > 0
    assert out["plan"]["executive_summary"]
    assert out["actions"], "должны появиться бизнес-действия из возможностей роста"
    assert out["plan"]["priority_actions"]


def test_generate_actions_dedup(db_session: Session) -> None:
    pid = _project(db_session, "exsvc4")
    _seed_revenue(db_session, pid)
    svc = _svc()
    svc.create_executive_plan(db_session, pid)
    before = len(svc.list_actions(db_session, pid))
    again = svc.generate_actions(db_session, pid)
    assert again == []  # повторная генерация не плодит дубликаты
    assert len(svc.list_actions(db_session, pid)) == before


def test_apply_requires_accept_and_confirmation(db_session: Session) -> None:
    pid = _project(db_session, "exsvc5")
    _seed_revenue(db_session, pid)
    svc = _svc()
    action_id = svc.create_executive_plan(db_session, pid)["actions"][0]["id"]

    with pytest.raises(AIExecutiveError):  # ещё не accepted
        svc.apply_action(db_session, action_id, confirmation=APPLY_CONFIRMATION)
    svc.accept_action(db_session, action_id)
    with pytest.raises(AIExecutiveError):  # нет подтверждения
        svc.apply_action(db_session, action_id, confirmation="")
    res = svc.apply_action(db_session, action_id, confirmation=APPLY_CONFIRMATION)
    assert res["live_enabled"] is False
    assert res["action"]["status"] == "applied"
    assert res["applied"]["draft_strategy"] in (True, False)


def test_apply_does_not_publish_or_touch_crm(db_session: Session) -> None:
    pid = _project(db_session, "exsvc6")
    _seed_revenue(db_session, pid)
    svc = _svc()
    action_id = svc.create_executive_plan(db_session, pid)["actions"][0]["id"]
    leads_before = db_session.query(AILeadEvent).count()
    svc.accept_action(db_session, action_id)
    svc.apply_action(db_session, action_id, confirmation=APPLY_CONFIRMATION)
    # apply не создаёт live-публикаций и не добавляет CRM-события.
    assert db_session.query(PostPublication).filter_by(status="published").count() == 0
    assert db_session.query(AILeadEvent).count() == leads_before


def test_reject_action(db_session: Session) -> None:
    pid = _project(db_session, "exsvc7")
    _seed_revenue(db_session, pid)
    svc = _svc()
    action_id = svc.create_executive_plan(db_session, pid)["actions"][0]["id"]
    rej = svc.reject_action(db_session, action_id)
    assert rej["status"] == "rejected"


def test_explain_and_summary(db_session: Session) -> None:
    pid = _project(db_session, "exsvc8")
    _seed_revenue(db_session, pid)
    svc = _svc()
    svc.create_executive_plan(db_session, pid)
    assert svc.explain_plan(db_session, pid)["reasons"]
    got = svc.get_plan(db_session, pid)
    assert got["has_plan"] is True and got["actions"]
    summary = svc.get_business_summary(db_session, pid)
    assert summary["has_plan"] is True


def test_missing_project_raises(db_session: Session) -> None:
    with pytest.raises(AIExecutiveError):
        _svc().analyze_business_state(db_session, 999999)


# --- Регрессии по итогам adversarial-review (v0.7.0) --- #


def test_reanalyze_keeps_plan_populated(db_session: Session) -> None:
    """Повторный analyze с теми же сигналами не должен давать пустой план (dedup-регрессия)."""
    pid = _project(db_session, "exsvc9")
    _seed_revenue(db_session, pid)
    svc = _svc()
    svc.create_executive_plan(db_session, pid)
    total_after_first = len(svc.list_actions(db_session, pid))
    out2 = svc.create_executive_plan(db_session, pid)
    # второй план не пустой: действия привязаны и приоритеты выставлены
    assert out2["actions"], "повторный план должен показывать открытые действия"
    assert out2["plan"]["priority_actions"]
    got = svc.get_plan(db_session, pid)
    assert got["actions"], "get_plan (последний план) должен показывать открытые действия"
    assert any("Приоритет" in r for r in svc.explain_plan(db_session, pid)["reasons"])
    # dedup: повторный analyze НЕ плодит дубликаты действий
    assert len(svc.list_actions(db_session, pid)) == total_after_first


def test_foreign_objective_binding_rejected(db_session: Session) -> None:
    """Нельзя построить план проекта P2 по цели чужого проекта P1 (tenant isolation)."""
    p1 = _project(db_session, "exsvcf1")
    p2 = _project(db_session, "exsvcf2")
    svc = _svc()
    obj_p1 = svc.create_objective(db_session, p1, type="revenue_growth", title="Цель P1")
    with pytest.raises(AIExecutiveError):
        svc.create_executive_plan(db_session, p2, objective_id=obj_p1["id"])
    # happy-path: своя цель привязывается
    obj_p2 = svc.create_objective(db_session, p2, type="lead_growth", title="Цель P2")
    out = svc.create_executive_plan(db_session, p2, objective_id=obj_p2["id"])
    assert out["plan"]["objective_id"] == obj_p2["id"]


def test_cross_status_dedup_applied_rejected_not_recreated(db_session: Session) -> None:
    """Applied/rejected действия не появляются заново при повторной генерации."""
    pid = _project(db_session, "exsvc10")
    _seed_revenue(db_session, pid)
    svc = _svc()
    actions = svc.create_executive_plan(db_session, pid)["actions"]
    assert len(actions) >= 2
    keys = {(a["action_type"], a["title"]) for a in actions}
    svc.reject_action(db_session, actions[0]["id"])
    svc.accept_action(db_session, actions[1]["id"])
    svc.apply_action(db_session, actions[1]["id"], confirmation=APPLY_CONFIRMATION)
    fresh = svc.generate_actions(db_session, pid)
    assert all((f["action_type"], f["title"]) not in keys for f in fresh)
    # каждый (type,title) остаётся в единственном экземпляре
    all_actions = svc.list_actions(db_session, pid)
    seen = [(a["action_type"], a["title"]) for a in all_actions]
    assert len(seen) == len(set(seen))


def test_apply_terminal_states_blocked(db_session: Session) -> None:
    """Терминальные статусы блокируют apply/accept/reject (двойной apply, apply-after-reject)."""
    pid = _project(db_session, "exsvc11")
    _seed_revenue(db_session, pid)
    svc = _svc()
    actions = svc.create_executive_plan(db_session, pid)["actions"]
    a_reject, a_apply = actions[0]["id"], actions[1]["id"]

    svc.reject_action(db_session, a_reject)
    with pytest.raises(AIExecutiveError):  # apply после reject
        svc.apply_action(db_session, a_reject, confirmation=APPLY_CONFIRMATION)

    svc.accept_action(db_session, a_apply)
    svc.apply_action(db_session, a_apply, confirmation=APPLY_CONFIRMATION)
    with pytest.raises(AIExecutiveError):  # повторный apply
        svc.apply_action(db_session, a_apply, confirmation=APPLY_CONFIRMATION)
    with pytest.raises(AIExecutiveError):  # accept после applied
        svc.accept_action(db_session, a_apply)
    with pytest.raises(AIExecutiveError):  # reject после applied
        svc.reject_action(db_session, a_apply)


def test_apply_draft_campaign_stays_non_live_draft(db_session: Session) -> None:
    """apply campaign-действия создаёт ЧЕРНОВИК кампании (draft), не live/active."""
    from app.models.ai_campaign import AICampaign
    from app.repositories import business_os_repository as repo

    pid = _project(db_session, "exsvc12")
    svc = _svc()
    # Строим campaign-действие напрямую (opportunity-паттерн кампании требует атрибуции).
    action = repo.create_action(
        db_session,
        project_id=pid,
        account_id=None,
        plan_id=None,
        action_type="campaign",
        title="Повторить успешную кампанию",
        priority=50.0,
        apply_payload={"draft_campaign": {"goal": "awareness", "name": "Кампания роста"}},
    )
    svc.accept_action(db_session, action.id)
    res = svc.apply_action(db_session, action.id, confirmation=APPLY_CONFIRMATION)
    assert res["applied"]["draft_campaign"] is True
    assert res["live_enabled"] is False
    campaigns = db_session.query(AICampaign).filter_by(project_id=pid).all()
    assert len(campaigns) == 1 and campaigns[0].status == "draft"


def test_reassign_moves_open_keeps_terminal(db_session: Session) -> None:
    """Повторный analyze: открытые (accepted) действия переезжают в новый план,
    терминальные (applied/rejected) остаются за старым планом."""
    from app.repositories import business_os_repository as repo

    pid = _project(db_session, "exsvc15")
    svc = _svc()
    plan1_id = svc.create_executive_plan(db_session, pid)["plan"]["id"]

    def mk(title: str, priority: float = 10.0) -> int:
        return repo.create_action(
            db_session,
            project_id=pid,
            account_id=None,
            plan_id=plan1_id,
            action_type="content",
            title=title,
            priority=priority,
        ).id

    a, b, c = mk("Отклонённое A"), mk("Применённое B"), mk("Открытое C")
    svc.reject_action(db_session, a)
    svc.accept_action(db_session, b)
    svc.apply_action(db_session, b, confirmation=APPLY_CONFIRMATION)
    svc.accept_action(db_session, c)  # accepted, но не applied → всё ещё открытое

    out2 = svc.create_executive_plan(db_session, pid)
    plan2_id = out2["plan"]["id"]
    # терминальные держатся за историческим планом
    assert repo.get_action(db_session, a).plan_id == plan1_id
    assert repo.get_action(db_session, b).plan_id == plan1_id
    # открытое accepted переехало в новый план
    assert repo.get_action(db_session, c).plan_id == plan2_id
    assert {x["title"] for x in out2["actions"]} == {"Открытое C"}
    assert out2["plan"]["priority_actions"] == ["Открытое C"]
    assert {x["title"] for x in svc.get_plan(db_session, pid)["actions"]} == {"Открытое C"}


def test_reassign_is_tenant_scoped(db_session: Session) -> None:
    """reassign при analyze проекта A не трогает действия проекта B."""
    from app.repositories import business_os_repository as repo

    pa = _project(db_session, "exsvca")
    pb = _project(db_session, "exsvcb")
    svc = _svc()
    svc.create_executive_plan(db_session, pa)
    b_plan_id = svc.create_executive_plan(db_session, pb)["plan"]["id"]
    b_action = repo.create_action(
        db_session,
        project_id=pb,
        account_id=None,
        plan_id=b_plan_id,
        action_type="content",
        title="Только B",
        priority=10.0,
    )
    svc.create_executive_plan(db_session, pa)  # повторный analyze A
    assert repo.get_action(db_session, b_action.id).plan_id == b_plan_id
    assert {x["title"] for x in svc.get_plan(db_session, pb)["actions"]} == {"Только B"}


def test_business_summary_open_count_includes_accepted(db_session: Session) -> None:
    """actions_open в сводке = generated+accepted (согласовано с get_plan/reassign)."""
    pid = _project(db_session, "exsvc16")
    _seed_revenue(db_session, pid)
    svc = _svc()
    actions = svc.create_executive_plan(db_session, pid)["actions"]
    total_open = len(actions)
    svc.accept_action(db_session, actions[0]["id"])  # accepted тоже «открытое»
    summary = svc.get_business_summary(db_session, pid)
    assert summary["actions_open"] == total_open


def test_long_title_is_deduped_after_db_truncation(db_session: Session) -> None:
    """Заголовок >255 символов не должен обходить дедуп (сравниваем с обрезанным до 255)."""
    pid = _project(db_session, "exsvc14")
    svc = _svc()
    opp = {
        "type": "content",
        "title": "Ж" * 400,
        "confidence": 80,
        "reason": "длинная возможность",
        "signals": ["content"],
    }
    first = svc._generate_actions(db_session, pid, None, [opp], None)
    second = svc._generate_actions(db_session, pid, None, [opp], None)
    assert len(first) == 1
    assert second == []  # дубликат не создаётся, несмотря на длину > 255
    assert len(svc.list_actions(db_session, pid)) == 1


def test_audit_log_written_for_plan_accept_apply(db_session: Session) -> None:
    """analyze/plan/accept/apply пишут события в AuditLog (project-scoped)."""
    from app.models.audit_log import AuditLogEntry

    pid = _project(db_session, "exsvc13")
    _seed_revenue(db_session, pid)
    svc = _svc()
    action_id = svc.create_executive_plan(db_session, pid)["actions"][0]["id"]
    svc.accept_action(db_session, action_id)
    svc.apply_action(db_session, action_id, confirmation=APPLY_CONFIRMATION)
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "business_os.plan_created" in actions
    assert "business_os.accepted" in actions
    assert "business_os.applied" in actions
