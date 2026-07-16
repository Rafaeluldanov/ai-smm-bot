"""Тесты полного E2E-пайплайна AI Business OS (v0.9.0, offline).

Инварианты:
- все 3 сценария (growth/recovery/optimization) проходят полный цикл и завершаются completed;
- каждый прогон даёт положительный score и корректный отчёт.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_os_demo_service import AIBusinessOSDemoService
from app.services.ai_business_os_report_service import AIBusinessOSReportService
from app.services.ai_business_os_scenario_service import (
    PIPELINE_STAGES,
    AIBusinessOSScenarioService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _workspace(db: Session, aid: int, uid: int) -> int:
    return AIBusinessOSDemoService(settings=_SETTINGS).create_demo_company(db, aid, user_id=uid)[
        "id"
    ]


def test_full_pipeline_all_scenarios(db_session: Session) -> None:
    aid, uid = _account(db_session, "e2e1")
    wid = _workspace(db_session, aid, uid)
    runner = AIBusinessOSScenarioService(settings=_SETTINGS)
    for scenario_type in ("growth", "recovery", "optimization"):
        sc = runner.run_scenario(db_session, wid, scenario_type, user_id=uid)
        assert sc["status"] == "completed"
        assert sc["score"] > 0.0
        passed = sum(1 for s in sc["result_data"]["stages"] if s["status"] == "pass")
        assert passed == len(PIPELINE_STAGES)  # весь пайплайн проходит


def test_e2e_produces_downstream_records(db_session: Session) -> None:
    """Полный цикл реально доводит до learning→optimization→governance (не пустой)."""
    aid, uid = _account(db_session, "e2e2")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(db_session, wid, "growth")
    stages = {s["stage"]: s for s in sc["result_data"]["stages"]}
    # обучение/оптимизация/governance произвели результат (цепочка дошла до конца)
    assert stages["learning"]["produced"]
    assert stages["optimization"]["produced"]
    assert stages["governance"]["produced"]


def test_e2e_report(db_session: Session) -> None:
    aid, uid = _account(db_session, "e2e3")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(
        db_session, wid, "growth", user_id=uid
    )
    report = AIBusinessOSReportService(settings=_SETTINGS).generate_report(
        db_session, sc["id"], user_id=uid
    )
    assert report["total_stages"] == len(PIPELINE_STAGES)
    assert report["passed_stages"] == len(PIPELINE_STAGES)
    assert report["overall_score"] > 0.0
    assert "MVP-READY" in report["verdict"] or "PASS" in report["verdict"]
