"""Тесты приоритизации бизнес-действий (v0.7.0).

priority = impact × confidence × urgency → 0..100; выше уверенность/вес типа → выше
приоритет; список действий отсортирован по убыванию приоритета.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_executive_service import AIExecutiveService
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def test_priority_score_bounds() -> None:
    for conf in (0, 25, 55, 85, 100, 200):
        score = AIExecutiveService._priority_score({"type": "conversion", "confidence": conf})
        assert 0.0 <= score <= 100.0


def test_higher_confidence_higher_priority() -> None:
    low = AIExecutiveService._priority_score({"type": "content", "confidence": 40})
    high = AIExecutiveService._priority_score({"type": "content", "confidence": 90})
    assert high > low


def test_type_weight_matters() -> None:
    # При равной уверенности более «сильный» тип получает не меньший приоритет.
    conversion = AIExecutiveService._priority_score({"type": "conversion", "confidence": 70})
    efficiency = AIExecutiveService._priority_score({"type": "efficiency", "confidence": 70})
    assert conversion > efficiency


def test_actions_sorted_by_priority(db_session: Session) -> None:
    pid = _project(db_session, "exprio")
    from app.repositories import post_repository

    post = post_repository.create_post(
        db_session,
        PostCreate(project_id=pid, title="Кейс", status="published", vk_text="x"),
    )
    AISalesIntelligenceService(settings=_SETTINGS).record_lead_event(
        db_session,
        pid,
        event_type="deal_won",
        post_id=post.id,
        platform_key="telegram",
        value=80000,
    )
    svc = AIExecutiveService(settings=_SETTINGS)
    svc.create_executive_plan(db_session, pid)
    actions = svc.prioritize_actions(db_session, pid)
    priorities = [a["priority"] for a in actions]
    assert priorities == sorted(priorities, reverse=True)


def test_plan_priority_actions_are_top_by_priority(db_session: Session) -> None:
    """plan.priority_actions = заголовки топ-3 открытых действий по убыванию приоритета."""
    from app.repositories import business_os_repository as repo

    pid = _project(db_session, "exprio2")
    svc = AIExecutiveService(settings=_SETTINGS)
    plan1_id = svc.create_executive_plan(db_session, pid)["plan"]["id"]
    # Три действия с различными приоритетами на первом плане.
    for title, prio in (("низкий", 30.0), ("высокий", 70.0), ("средний", 50.0)):
        repo.create_action(
            db_session,
            project_id=pid,
            account_id=None,
            plan_id=plan1_id,
            action_type="content",
            title=title,
            priority=prio,
        )
    out = svc.create_executive_plan(db_session, pid)
    assert out["plan"]["priority_actions"] == ["высокий", "средний", "низкий"]
    returned = [a["priority"] for a in out["actions"]]
    assert returned == sorted(returned, reverse=True)
