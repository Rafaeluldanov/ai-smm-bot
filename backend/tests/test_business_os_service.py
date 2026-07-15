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
