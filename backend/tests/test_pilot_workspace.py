"""Тесты pilot-воркспейса AI Business OS Pilot (v0.9.1, offline).

Инварианты:
- workspace создаётся участнику; member-check FAIL CLOSED (чужой аккаунт); pilot_mode gate; аудит.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    AIBusinessPilotService,
    PilotModeDisabledError,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc(settings: Settings = _SETTINGS) -> AIBusinessPilotService:
    return AIBusinessPilotService(settings=settings)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def test_create_workspace(db_session: Session) -> None:
    aid, uid = _account(db_session, "pw1")
    ws = _svc().create_pilot_workspace(db_session, aid, company_name="TEEON Pilot", user_id=uid)
    assert ws["company_name"] == "TEEON Pilot" and ws["status"] == "active"
    assert ws["account_id"] == aid and ws["created_by"] == uid


def test_member_check_fail_closed_cross_account(db_session: Session) -> None:
    """Создать воркспейс под аккаунт A пользователем аккаунта B запрещено."""
    aid_a, _uid_a = _account(db_session, "pw2a")
    _aid_b, uid_b = _account(db_session, "pw2b")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_pilot_workspace(db_session, aid_a, company_name="X", user_id=uid_b)


def test_create_requires_user(db_session: Session) -> None:
    aid, _uid = _account(db_session, "pw3")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_pilot_workspace(db_session, aid, company_name="X", user_id=None)


def test_pilot_mode_gate(db_session: Session) -> None:
    aid, uid = _account(db_session, "pw4")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        _svc(off).create_pilot_workspace(db_session, aid, company_name="X", user_id=uid)


def test_list_workspaces_scoped(db_session: Session) -> None:
    aid, uid = _account(db_session, "pw5")
    svc = _svc()
    svc.create_pilot_workspace(db_session, aid, company_name="A", user_id=uid)
    lst = svc.list_workspaces(db_session, account_id=aid)
    assert len(lst) == 1 and lst[0]["account_id"] == aid


def test_audit_workspace_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    aid, uid = _account(db_session, "pw6")
    _svc().create_pilot_workspace(db_session, aid, company_name="X", user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.workspace_created" in actions
