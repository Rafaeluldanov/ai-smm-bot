"""Тесты бизнес-целей пилота (v1.0.0, offline).

Инварианты (Part 2/15): цель создаётся с корректными полями/дефолтами; хранится per-workspace;
public view без секретов; pilot_mode gate; аудит goal_created.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.audit_log import AuditLogEntry
from app.models.pilot_goal import PILOT_GOAL_STATUSES, PILOT_PRIORITIES
from app.repositories import account_repository, user_repository
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import PilotModeDisabledError
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_GOAL_KEYS = {
    "id",
    "workspace_id",
    "title",
    "description",
    "current_value",
    "target_value",
    "unit",
    "deadline",
    "priority",
    "status",
    "created_at",
    "updated_at",
}


def _svc(settings: Settings = _SETTINGS) -> AIPilotOnboardingService:
    return AIPilotOnboardingService(settings=settings)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _workspace(db: Session, slug: str) -> tuple[int, int]:
    aid, uid = _account(db, slug)
    pilot = _svc().create_company_pilot(db, aid, company_name="Co", user_id=uid, goals=[], kpis=[])
    return pilot["workspace"]["id"], uid


def test_defaults_and_constants() -> None:
    assert "active" in PILOT_GOAL_STATUSES and "completed" in PILOT_GOAL_STATUSES
    assert "high" in PILOT_PRIORITIES and "medium" in PILOT_PRIORITIES


def test_create_goal(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "goal1")
    goal = _svc().create_goal(
        db_session,
        wid,
        {
            "title": "Выручка x2",
            "current_value": 5.0,
            "target_value": 10.0,
            "unit": "млн",
            "priority": "high",
        },
        user_id=uid,
    )
    assert goal["title"] == "Выручка x2"
    assert goal["current_value"] == 5.0 and goal["target_value"] == 10.0
    assert goal["priority"] == "high" and goal["status"] == "active"
    assert set(goal) == _GOAL_KEYS


def test_goal_defaults(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "goal2")
    goal = _svc().create_goal(db_session, wid, {}, user_id=uid)
    assert goal["title"] == "Бизнес-цель"
    assert goal["priority"] == "medium"


def test_goal_scoped_to_workspace(db_session: Session) -> None:
    wid1, uid1 = _workspace(db_session, "goal3a")
    wid2, uid2 = _workspace(db_session, "goal3b")
    _svc().create_goal(db_session, wid1, {"title": "A"}, user_id=uid1)
    assert len(repo.list_goals(db_session, wid1)) == 1
    assert len(repo.list_goals(db_session, wid2)) == 0


def test_goal_invalid_priority_rejected(db_session: Session) -> None:
    """Недопустимый/слишком длинный priority → AIBusinessPilotError (400, не 500 из БД)."""
    from app.services.ai_business_pilot_service import AIBusinessPilotError

    wid, uid = _workspace(db_session, "goal6")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_goal(db_session, wid, {"title": "X", "priority": "p" * 60}, user_id=uid)


def test_goal_pilot_mode_gate(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "goal4")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        _svc(off).create_goal(db_session, wid, {"title": "X"}, user_id=uid)


def test_goal_audit(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "goal5")
    _svc().create_goal(db_session, wid, {"title": "X"}, user_id=uid)
    actions = [e.action for e in db_session.query(AuditLogEntry).all()]
    assert "pilot.goal_created" in actions
