"""Тесты E2E scenario runner AI Business OS (v0.9.0, offline).

Инварианты:
- growth-сценарий проходит все этапы AI-цепочки (Decision→…→Governance) со статусом pass;
- сценарий выполняется на ИЗОЛИРОВАННОМ demo-проекте; аудит.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.ai_business_os_demo_service import AIBusinessOSDemoService
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
    ws = AIBusinessOSDemoService(settings=_SETTINGS).create_demo_company(db, aid, user_id=uid)
    return ws["id"]


def test_growth_scenario_all_stages(db_session: Session) -> None:
    aid, uid = _account(db_session, "sc1")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_growth_scenario(
        db_session, wid, user_id=uid
    )
    assert sc["status"] == "completed"
    stages = {s["stage"]: s for s in sc["result_data"]["stages"]}
    # все 8 этапов присутствуют и в правильном порядке
    assert [s["stage"] for s in sc["result_data"]["stages"]] == list(PIPELINE_STAGES)
    for name in PIPELINE_STAGES:
        assert stages[name]["status"] == "pass", f"{name}: {stages[name]['detail']}"


def test_growth_pipeline_layers_covered(db_session: Session) -> None:
    """Явно проверяем ключевые слои цепочки."""
    aid, uid = _account(db_session, "sc2")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_growth_scenario(db_session, wid)
    names = {s["stage"] for s in sc["result_data"]["stages"]}
    for layer in (
        "decision",
        "forecast",
        "planner",
        "execution",
        "performance",
        "learning",
        "optimization",
        "governance",
    ):
        assert layer in names


def test_scenario_isolated_demo_project(db_session: Session) -> None:
    """Сценарий создаёт ОТДЕЛЬНЫЙ demo-проект (slug demo-*), не трогая реальные."""
    from app.repositories import project_repository

    aid, uid = _account(db_session, "sc3")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(db_session, wid, "growth")
    pid = sc["result_data"]["project_id"]
    project = project_repository.get_project_by_id(db_session, pid)
    assert project is not None and project.slug.startswith("demo-")


def test_scenario_score_positive(db_session: Session) -> None:
    aid, uid = _account(db_session, "sc4")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(db_session, wid, "growth")
    assert sc["score"] > 0.0


def test_audit_scenario_lifecycle(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    aid, uid = _account(db_session, "sc5")
    wid = _workspace(db_session, aid, uid)
    AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(
        db_session, wid, "growth", user_id=uid
    )
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "demo.scenario_started" in actions and "demo.scenario_completed" in actions


def test_fatal_pipeline_does_not_crash(db_session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Фатальная ошибка пайплайна не роняет запрос — прогон сохраняется как failed."""
    aid, uid = _account(db_session, "sc6")
    wid = _workspace(db_session, aid, uid)
    svc = AIBusinessOSScenarioService(settings=_SETTINGS)

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("pipeline down")

    monkeypatch.setattr(svc, "_run_pipeline", _boom)
    sc = svc.run_scenario(db_session, wid, "growth", user_id=uid)  # не падает
    assert sc["status"] == "failed"


def test_save_result_failure_does_not_crash(db_session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Сбой сохранения (отравленная сессия) не роняет запрос (defensive rollback + retry)."""
    from app.repositories import demo_testing_repository as dtr

    aid, uid = _account(db_session, "sc7")
    wid = _workspace(db_session, aid, uid)
    svc = AIBusinessOSScenarioService(settings=_SETTINGS)
    orig = dtr.save_result
    calls = {"n": 0}

    def _flaky(*a: object, **k: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("commit poisoned")
        return orig(*a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(dtr, "save_result", _flaky)
    sc = svc.run_scenario(db_session, wid, "growth", user_id=uid)  # не падает
    assert sc is not None and calls["n"] >= 2  # был retry после rollback
