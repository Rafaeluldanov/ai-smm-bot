"""Тесты CEO Dashboard пилота (v0.9.1, offline).

Инварианты:
- generate_dashboard возвращает score/ситуацию/риски/возможности/действия/прогноз; аудит;
- без прогона — осмысленный фолбэк (has_data=false).
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
from app.services.ai_business_pilot_service import AIBusinessPilotService
from app.services.ai_ceo_dashboard_service import AICEODashboardService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _pilot(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    pilot = AIBusinessPilotService(settings=_SETTINGS)
    ws = pilot.create_pilot_workspace(db, account.id, company_name="TEEON Pilot", user_id=owner.id)
    pilot.create_business_profile(
        db, ws["id"], current_revenue=5_000_000, target_revenue=10_000_000, user_id=owner.id
    )
    return ws["id"], owner.id


def _dash() -> AICEODashboardService:
    return AICEODashboardService(settings=_SETTINGS)


def test_dashboard_after_run(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "cd1")
    AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(
        db_session, wid, user_id=uid
    )
    dash = _dash().generate_dashboard(db_session, wid, user_id=uid)
    for key in (
        "business_score",
        "current_state",
        "risks",
        "opportunities",
        "today_actions",
        "forecast",
    ):
        assert key in dash
    assert dash["has_data"] is True
    assert dash["business_score"] > 0.0  # 5М/10М → ~50
    assert dash["forecast"].get("available") is True


def test_dashboard_reflects_revenue_gap(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "cd2")
    AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(db_session, wid)
    dash = _dash().generate_dashboard(db_session, wid)
    assert dash["risks"]  # разрыв выручки → есть риск
    assert dash["today_actions"]  # действия непустые


def test_dashboard_no_data_fallback(db_session: Session) -> None:
    """Без прогона — dashboard строится, has_data=false, осмысленный фолбэк."""
    wid, uid = _pilot(db_session, "cd3")
    dash = _dash().generate_dashboard(db_session, wid)
    assert dash["has_data"] is False
    assert dash["business_score"] == 0.0
    assert dash["today_actions"]  # фолбэк-действие


def test_audit_dashboard_generated(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    wid, uid = _pilot(db_session, "cd4")
    _dash().generate_dashboard(db_session, wid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.dashboard_generated" in actions
