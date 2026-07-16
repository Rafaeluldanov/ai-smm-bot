"""Тесты pilot-сценария AI Business OS Pilot (v0.9.1, offline).

Инварианты:
- run_growth_pilot проходит все 8 этапов AI-цепочки (переиспользует v0.9.0 pipeline);
- прогон на ОТДЕЛЬНОМ pilot-проекте (slug pilot-ws-*); score; аудит scenario_started.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_os_scenario_service import PIPELINE_STAGES
from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
from app.services.ai_business_pilot_service import AIBusinessPilotService, pilot_project_slug

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _workspace(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    ws = AIBusinessPilotService(settings=_SETTINGS).create_pilot_workspace(
        db, account.id, company_name="TEEON Pilot", user_id=owner.id
    )
    return ws["id"], owner.id


def _run(db: Session, wid: int, uid: int) -> dict:
    return AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(db, wid, user_id=uid)


def test_growth_pilot_all_stages(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "ps1")
    run = _run(db_session, wid, uid)
    assert run["status"] == "completed"
    assert [s["stage"] for s in run["stages"]] == list(PIPELINE_STAGES)
    passed = sum(1 for s in run["stages"] if s["status"] == "pass")
    assert passed == len(PIPELINE_STAGES)


def test_pilot_isolated_project(db_session: Session) -> None:
    from app.repositories import project_repository

    wid, uid = _workspace(db_session, "ps2")
    run = _run(db_session, wid, uid)
    project = project_repository.get_project_by_id(db_session, run["project_id"])
    assert project is not None and project.slug == pilot_project_slug(wid)


def test_pilot_run_reuses_same_project(db_session: Session) -> None:
    """Повторный прогон использует ТОТ ЖЕ pilot-проект (детерминированный slug)."""
    wid, uid = _workspace(db_session, "ps3")
    first = _run(db_session, wid, uid)
    second = _run(db_session, wid, uid)
    assert first["project_id"] == second["project_id"]


def test_pilot_score_positive(db_session: Session) -> None:
    wid, uid = _workspace(db_session, "ps4")
    run = _run(db_session, wid, uid)
    assert run["score"] > 0.0


def test_audit_scenario_started(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    wid, uid = _workspace(db_session, "ps5")
    _run(db_session, wid, uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "pilot.scenario_started" in actions
