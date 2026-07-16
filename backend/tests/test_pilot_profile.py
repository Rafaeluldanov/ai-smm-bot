"""Тесты бизнес-профиля пилота (v0.9.1, offline).

Инварианты:
- профиль создаётся (продукты/команда/выручка/цель); get_profile — последний; update; аудит.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import AIBusinessPilotService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIBusinessPilotService:
    return AIBusinessPilotService(settings=_SETTINGS)


def _workspace(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    ws = _svc().create_pilot_workspace(db, account.id, company_name="TEEON Pilot", user_id=owner.id)
    return ws["id"], owner.id


def test_create_profile(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "pp1")
    prof = _svc().create_business_profile(
        db_session,
        wid,
        products=["hoodie", "tee"],
        team={"size": 25},
        current_revenue=5_000_000,
        target_revenue=10_000_000,
        user_id=uid,
    )
    assert prof["current_revenue"] == 5_000_000 and prof["target_revenue"] == 10_000_000
    assert prof["products"] == ["hoodie", "tee"] and prof["team"] == {"size": 25}


def test_get_profile_latest(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "pp2")
    svc = _svc()
    svc.create_business_profile(db_session, wid, current_revenue=1.0, user_id=uid)
    svc.create_business_profile(db_session, wid, current_revenue=2.0, user_id=uid)
    profile = repo.get_profile(db_session, wid)
    assert profile is not None and profile.current_revenue == 2.0  # последний


def test_get_workspace_includes_profile(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "pp3")
    svc = _svc()
    svc.create_business_profile(db_session, wid, current_revenue=5.0, user_id=uid)
    out = svc.get_workspace(db_session, wid)
    assert out["profile"] is not None and out["profile"]["current_revenue"] == 5.0


def test_update_profile_whitelist(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "pp4")
    profile = repo.create_profile(db_session, workspace_id=wid, current_revenue=5.0)
    repo.update_profile(db_session, profile, target_revenue=99.0, workspace_id=999)
    assert profile.target_revenue == 99.0 and profile.workspace_id == wid  # workspace_id не тронут


def test_audit_profile_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    wid, uid = _workspace(db_session, "pp5")
    _svc().create_business_profile(db_session, wid, current_revenue=5.0, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.profile_created" in actions
