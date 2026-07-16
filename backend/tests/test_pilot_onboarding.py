"""Тесты онбординга компании в бизнес-пилот (v1.0.0, offline).

Инварианты (Part 1/15): онбординг создаёт workspace→profile→goal→KPI участнику аккаунта;
member-check FAIL CLOSED (чужой аккаунт); pilot_mode gate; аудит goal_created/kpi_created.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.audit_log import AuditLogEntry
from app.repositories import account_repository, user_repository
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import AIBusinessPilotError, PilotModeDisabledError
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc(settings: Settings = _SETTINGS) -> AIPilotOnboardingService:
    return AIPilotOnboardingService(settings=settings)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def test_onboarding_creates_full_pilot(db_session: Session) -> None:
    aid, uid = _account(db_session, "onb1")
    pilot = _svc().create_company_pilot(
        db_session, aid, company_name="TEEON Pilot", industry="apparel", user_id=uid
    )
    assert pilot["workspace"]["account_id"] == aid
    assert pilot["workspace"]["company_name"] == "TEEON Pilot"
    assert pilot["profile"]["current_revenue"] == 5_000_000.0
    assert pilot["profile"]["target_revenue"] == 10_000_000.0
    assert len(pilot["goals"]) == 1
    assert len(pilot["kpis"]) == 2
    # Реально записалось в БД.
    wid = pilot["workspace"]["id"]
    assert len(repo.list_goals(db_session, wid)) == 1
    assert len(repo.list_kpis(db_session, wid)) == 2


def test_onboarding_custom_goals_kpis(db_session: Session) -> None:
    aid, uid = _account(db_session, "onb2")
    pilot = _svc().create_company_pilot(
        db_session,
        aid,
        company_name="Custom Co",
        profile={"current_revenue": 1_000_000.0, "target_revenue": 3_000_000.0},
        goals=[{"title": "Рост x3", "current_value": 1.0, "target_value": 3.0, "unit": "x"}],
        kpis=[{"name": "LTV", "current_value": 100.0, "target_value": 200.0, "unit": "руб"}],
        user_id=uid,
    )
    assert pilot["profile"]["current_revenue"] == 1_000_000.0
    assert len(pilot["goals"]) == 1 and pilot["goals"][0]["title"] == "Рост x3"
    assert len(pilot["kpis"]) == 1 and pilot["kpis"][0]["name"] == "LTV"


def test_onboarding_member_check_fail_closed(db_session: Session) -> None:
    """Пользователь аккаунта B не может завести пилот под аккаунт A."""
    aid_a, _uid_a = _account(db_session, "onb3a")
    _aid_b, uid_b = _account(db_session, "onb3b")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(db_session, aid_a, company_name="X", user_id=uid_b)


def test_onboarding_requires_user(db_session: Session) -> None:
    aid, _uid = _account(db_session, "onb4")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(db_session, aid, company_name="X", user_id=None)


def test_onboarding_invalid_input_is_atomic(db_session: Session) -> None:
    """Невалидное число в KPI → AIBusinessPilotError (400); workspace/profile не создаются."""
    from app.repositories import pilot_repository as repo

    aid, uid = _account(db_session, "onb7")
    before = len(repo.list_workspaces(db_session, account_id=aid))
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(
            db_session,
            aid,
            company_name="X",
            kpis=[{"name": "K", "current_value": "not-a-number"}],
            user_id=uid,
        )
    # Валидация до первой записи → пилот-«сирота» не остаётся.
    assert len(repo.list_workspaces(db_session, account_id=aid)) == before


def test_onboarding_malformed_container_rejected(db_session: Session) -> None:
    """Неверная ФОРМА запроса (profile/goals не dict) → AIBusinessPilotError (400, не 500)."""
    aid, uid = _account(db_session, "onb9")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(db_session, aid, company_name="X", profile="oops", user_id=uid)  # type: ignore[arg-type]
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(db_session, aid, company_name="X", goals=[123], user_id=uid)  # type: ignore[list-item]


def test_onboarding_invalid_priority_rejected(db_session: Session) -> None:
    aid, uid = _account(db_session, "onb8")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_company_pilot(
            db_session,
            aid,
            company_name="X",
            goals=[{"title": "G", "priority": "ultra-mega-critical"}],
            user_id=uid,
        )


def test_onboarding_pilot_mode_gate(db_session: Session) -> None:
    aid, uid = _account(db_session, "onb5")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        _svc(off).create_company_pilot(db_session, aid, company_name="X", user_id=uid)


def test_onboarding_audit_trail(db_session: Session) -> None:
    aid, uid = _account(db_session, "onb6")
    _svc().create_company_pilot(db_session, aid, company_name="X", user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.workspace_created" in actions
    assert "pilot.profile_created" in actions
    assert "pilot.goal_created" in actions
    assert "pilot.kpi_created" in actions
