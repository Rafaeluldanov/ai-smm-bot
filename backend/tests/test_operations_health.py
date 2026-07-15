"""Тесты расчёта health-score и детекции рисков (v0.7.3).

health = Growth + Revenue + Execution + Workflow − Risk Penalty → 0..100; статус по порогам.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import operations_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_operations_control_service import AIOperationsControlService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOperationsControlService:
    return AIOperationsControlService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def test_health_weighted_formula() -> None:
    svc = _svc()
    comp = {"growth": 100.0, "revenue": 100.0, "execution": 100.0, "workflow_progress": 100.0}
    assert svc.calculate_health_score(comp, 0.0) == 100.0
    zero = {"growth": 0.0, "revenue": 0.0, "execution": 0.0, "workflow_progress": 0.0}
    assert svc.calculate_health_score(zero, 0.0) == 0.0
    # штраф вычитается и клампится в [0..100]
    assert svc.calculate_health_score(comp, 200.0) == 0.0


def test_health_status_thresholds() -> None:
    svc = _svc()
    high = {"growth": 100.0, "revenue": 100.0, "execution": 100.0, "workflow_progress": 100.0}
    low = {"growth": 10.0, "revenue": 0.0, "execution": 10.0, "workflow_progress": 0.0}
    assert svc.calculate_health_score(high, 0.0) >= 70  # healthy-диапазон
    assert svc.calculate_health_score(low, 40.0) < 40  # critical-диапазон


def test_missing_data_risk_when_no_signals(db_session: Session) -> None:
    """Проект без выручки/лидов → риск missing_data."""
    pid = _project(db_session, "opsh1")
    out = _svc().build_operations_snapshot(db_session, pid)
    types = {r["risk_type"] for r in out["risks"]}
    assert "missing_data" in types


def test_risk_penalty_lowers_health(db_session: Session) -> None:
    """Открытые риски снижают health-score (risk_penalty > 0)."""
    pid = _project(db_session, "opsh2")
    out = _svc().build_operations_snapshot(db_session, pid)
    metrics = out["snapshot"]["metrics"]
    assert metrics["risk_penalty"] > 0
    assert out["snapshot"]["risk_count"] >= 1


def test_health_components_from_active_workflows(db_session: Session) -> None:
    """При активном процессе execution/workflow_progress берутся из реального health, не 70."""
    from app.services.ai_workflow_manager_service import AIWorkflowManagerService

    pid = _project(db_session, "opsh4")
    wf = AIWorkflowManagerService(settings=_SETTINGS)
    wid = wf.create_workflow_from_goal(
        db_session, pid, name="P", workflow_type="sales", status="active"
    )["id"]
    step = wf.generate_workflow_steps(db_session, wid)[0]["id"]
    wf.create_blocker(db_session, wid, blocker_type="approval", title="Ждём", step_id=step)
    out = _svc().build_operations_snapshot(db_session, pid)
    m = out["snapshot"]["metrics"]
    # 0% прогресса не подменяется нейтральными 70; execution отражает health процесса
    assert m["workflow_progress"] == 0.0
    assert m["execution"] != 70.0


def test_content_gap_branches_with_business_data(db_session: Session) -> None:
    """При наличии данных: efficiency 0.0 → нет; (0,30) → есть; ≥30 → нет; weak_areas → есть."""
    svc = _svc()

    def detect(slug: str, efficiency: float, weak: list) -> set[str]:
        pid = _project(db_session, slug)
        signals = {
            "workflow": {},
            "sales": {"revenue": 5.0, "leads": 1},  # есть бизнес-данные
            "prev": {},
            "content": {"content_efficiency": efficiency, "weak_areas": weak},
        }
        svc._detect_risks(db_session, pid, signals, None)
        return {r["risk_type"] for r in svc.list_active_risks(db_session, pid)}

    assert "content_gap" not in detect("opsh5a", 0.0, [])  # 0.0 = нет данных по контенту
    assert "content_gap" in detect("opsh5b", 15.0, [])  # низкая-но-ненулевая эффективность
    assert "content_gap" not in detect("opsh5c", 50.0, [])  # здоровый контент
    assert "content_gap" not in detect("opsh5d", 30.0, [])  # граница исключительна
    assert "content_gap" in detect("opsh5e", 0.0, ["слабо"])  # реальные слабые темы


def test_no_data_project_only_missing_data_not_content_gap(db_session: Session) -> None:
    """Виртуальный no-data проект через реальный pipeline: только missing_data, без content_gap."""
    pid = _project(db_session, "opsh6")  # ни выручки, ни лидов, ни контента
    out = _svc().build_operations_snapshot(db_session, pid)
    types = {r["risk_type"] for r in out["risks"]}
    assert "missing_data" in types
    assert "content_gap" not in types  # data-scarcity не должна выдаваться за провал контента


def test_snapshot_persisted_state(db_session: Session) -> None:
    """Снапшот сохраняет метрики и подсостояния (для тренда/сравнения)."""
    pid = _project(db_session, "opsh3")
    _svc().build_operations_snapshot(db_session, pid)
    snap = repo.get_latest_snapshot(db_session, pid)
    assert snap is not None
    assert "growth" in (snap.metrics or {})
    assert isinstance(snap.workflow_state, dict)
