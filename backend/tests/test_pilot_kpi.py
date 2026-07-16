"""Тесты KPI пилота (v1.0.0, offline).

Инварианты (Part 3/15): KPI создаётся с корректными полями/дефолтами; per-workspace; public view без
секретов; pilot_mode gate; аудит kpi_created.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.audit_log import AuditLogEntry
from app.models.pilot_kpi import PILOT_KPI_FREQUENCIES, PILOT_KPI_STATUSES
from app.repositories import account_repository, user_repository
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import PilotModeDisabledError
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_KPI_KEYS = {
    "id",
    "workspace_id",
    "name",
    "current_value",
    "target_value",
    "unit",
    "frequency",
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


def test_kpi_constants() -> None:
    assert "active" in PILOT_KPI_STATUSES
    assert "monthly" in PILOT_KPI_FREQUENCIES and "weekly" in PILOT_KPI_FREQUENCIES


def test_create_kpi(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "kpi1")
    kpi = _svc().create_kpi(
        db_session,
        wid,
        {
            "name": "Конверсия",
            "current_value": 2.0,
            "target_value": 4.0,
            "unit": "%",
            "frequency": "weekly",
        },
        user_id=uid,
    )
    assert kpi["name"] == "Конверсия"
    assert kpi["current_value"] == 2.0 and kpi["target_value"] == 4.0
    assert kpi["frequency"] == "weekly" and kpi["status"] == "active"
    assert set(kpi) == _KPI_KEYS


def test_kpi_defaults(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "kpi2")
    kpi = _svc().create_kpi(db_session, wid, {}, user_id=uid)
    assert kpi["name"] == "KPI"
    assert kpi["frequency"] == "monthly"


def test_kpi_scoped_to_workspace(db_session: Session) -> None:
    wid1, uid1 = _workspace(db_session, "kpi3a")
    wid2, _uid2 = _workspace(db_session, "kpi3b")
    _svc().create_kpi(db_session, wid1, {"name": "A"}, user_id=uid1)
    assert len(repo.list_kpis(db_session, wid1)) == 1
    assert len(repo.list_kpis(db_session, wid2)) == 0


def test_kpi_invalid_frequency_rejected(db_session: Session) -> None:
    """Недопустимая/слишком длинная frequency → AIBusinessPilotError (400, не 500 из БД)."""
    from app.services.ai_business_pilot_service import AIBusinessPilotError

    wid, uid = _workspace(db_session, "kpi6")
    with pytest.raises(AIBusinessPilotError):
        _svc().create_kpi(db_session, wid, {"name": "X", "frequency": "f" * 60}, user_id=uid)


def test_kpi_pilot_mode_gate(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "kpi4")
    off = Settings(media_proxy_public_base_url="https://m.example.com", pilot_mode=False)
    with pytest.raises(PilotModeDisabledError):
        _svc(off).create_kpi(db_session, wid, {"name": "X"}, user_id=uid)


def test_kpi_audit(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "kpi5")
    _svc().create_kpi(db_session, wid, {"name": "X"}, user_id=uid)
    actions = [e.action for e in db_session.query(AuditLogEntry).all()]
    assert "pilot.kpi_created" in actions
