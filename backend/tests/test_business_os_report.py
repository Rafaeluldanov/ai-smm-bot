"""Тесты генерации отчёта AI Business OS (v0.9.0, offline).

Инварианты:
- отчёт содержит все этапы пайплайна с PASS/FAIL, overall score, verdict; аудит report_created.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.repositories import demo_testing_repository as repo
from app.services.ai_business_os_report_service import AIBusinessOSReportService
from app.services.ai_business_os_scenario_service import PIPELINE_STAGES

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _scenario_with_result(db: Session, aid: int, *, stages: list[dict], score: float) -> int:
    ws = repo.create_workspace(db, account_id=aid, name="w")
    scenario = repo.create_scenario(
        db,
        workspace_id=ws.id,
        scenario_type="growth",
        status="completed",
        result_data={"stages": stages, "score": score},
        score=score,
    )
    return scenario.id


def _svc() -> AIBusinessOSReportService:
    return AIBusinessOSReportService(settings=_SETTINGS)


def test_report_all_pass(db_session: Session) -> None:
    aid, _ = _account(db_session, "rp1")
    stages = [{"stage": n, "status": "pass", "produced": True} for n in PIPELINE_STAGES]
    sid = _scenario_with_result(db_session, aid, stages=stages, score=96.0)
    report = _svc().generate_report(db_session, sid)
    assert report["total_stages"] == len(PIPELINE_STAGES)
    assert report["passed_stages"] == len(PIPELINE_STAGES)
    assert all(s["result"] == "PASS" for s in report["stages"])
    assert "MVP-READY" in report["verdict"]


def test_report_marks_failures(db_session: Session) -> None:
    aid, _ = _account(db_session, "rp2")
    stages = [{"stage": n, "status": "pass", "produced": True} for n in PIPELINE_STAGES]
    stages[3] = {"stage": PIPELINE_STAGES[3], "status": "fail", "produced": False, "detail": "boom"}
    stages[5] = {"stage": PIPELINE_STAGES[5], "status": "fail", "produced": False, "detail": "boom"}
    sid = _scenario_with_result(db_session, aid, stages=stages, score=60.0)
    report = _svc().generate_report(db_session, sid)
    fails = [s for s in report["stages"] if s["result"] == "FAIL"]
    assert len(fails) == 2
    assert "ATTENTION" in report["verdict"]


def test_report_missing_scenario_raises(db_session: Session) -> None:
    import pytest

    from app.services.ai_business_os_demo_service import AIBusinessOSDemoError

    with pytest.raises(AIBusinessOSDemoError):
        _svc().generate_report(db_session, 999999)


def test_audit_report_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    aid, _ = _account(db_session, "rp3")
    stages = [{"stage": n, "status": "pass", "produced": True} for n in PIPELINE_STAGES]
    sid = _scenario_with_result(db_session, aid, stages=stages, score=96.0)
    _svc().generate_report(db_session, sid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "demo.report_created" in actions
