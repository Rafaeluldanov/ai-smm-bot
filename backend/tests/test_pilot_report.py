"""Тесты отчёта по пилоту (v0.9.1, offline).

Инварианты:
- generate_pilot_report содержит компанию/цель/состояние/score/риски/возможности/рекомендации/
  прогноз/шаги; аудит report_created.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_pilot_report_service import AIBusinessPilotReportService
from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
from app.services.ai_business_pilot_service import AIBusinessPilotService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _pilot(db: Session, slug: str, *, run: bool = True) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    pilot = AIBusinessPilotService(settings=_SETTINGS)
    ws = pilot.create_pilot_workspace(db, account.id, company_name="TEEON Pilot", user_id=owner.id)
    pilot.create_business_profile(
        db, ws["id"], current_revenue=5_000_000, target_revenue=10_000_000, user_id=owner.id
    )
    if run:
        AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(db, ws["id"])
    return ws["id"], owner.id


def _svc() -> AIBusinessPilotReportService:
    return AIBusinessPilotReportService(settings=_SETTINGS)


def test_report_structure(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "pr1")
    report = _svc().generate_pilot_report(db_session, wid, user_id=uid)
    for key in (
        "company",
        "goal",
        "business_state",
        "performance_score",
        "risks",
        "opportunities",
        "ai_recommendations",
        "forecast",
        "next_steps",
    ):
        assert key in report
    assert report["company"]["name"] == "TEEON Pilot"
    assert report["goal"]["target_revenue"] == 10_000_000
    assert report["performance_score"] > 0.0
    assert report["next_steps"]


def test_report_without_run(db_session: Session) -> None:
    """Отчёт до прогона: строится, содержит шаг «запустить анализ»."""
    wid, uid = _pilot(db_session, "pr2", run=False)
    report = _svc().generate_pilot_report(db_session, wid)
    assert report["has_data"] is False
    joined = " ".join(report["next_steps"]).lower()
    assert "pilot-анализ" in joined or "запустить" in joined


def test_audit_report_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    wid, uid = _pilot(db_session, "pr3")
    _svc().generate_pilot_report(db_session, wid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.report_created" in actions
