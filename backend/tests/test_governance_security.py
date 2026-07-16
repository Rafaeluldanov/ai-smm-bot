"""Тесты безопасности AI Optimization Governance (v0.8.2, offline).

Инварианты (Part 17): governance/управляющий слой — только управляет статусами/владельцами/impact.
Запрещено: авто-утверждать; авто-запускать; менять бизнес/KPI/CRM/бюджет; выполнять
задачи. Проверяем: billing 0 (config+поведение); цикл/approve НЕ создают бизнес-объектов; analyze НЕ
авто-утверждает; owner FAIL CLOSED (чужой аккаунт); секретов нет; tenant isolation.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.models.billing import UsageEvent
from app.models.business_objective import BusinessObjective
from app.models.business_workflow import BusinessWorkflow
from app.models.crm_bot_smm import CrmSmmResource
from app.models.execution_plan import ExecutionPlan
from app.models.execution_task import ExecutionTask
from app.models.experiment_result import ExperimentResult
from app.models.optimization_experiment import OptimizationExperiment
from app.models.post_publication import PostPublication
from app.models.quarter_objective import QuarterObjective
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_governance_repository as gov_repo
from app.repositories import optimization_repository as opt_repo
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_optimization_governance_service import (
    AIOptimizationGovernanceError,
    AIOptimizationGovernanceService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")

_PROTECTED_MODELS = (
    PostPublication,
    BusinessWorkflow,
    ExecutionPlan,
    ExecutionTask,
    BusinessObjective,
    QuarterObjective,
    CrmSmmResource,
    # v0.8.1 эксперименты — governance НЕ создаёт/не запускает их.
    OptimizationExperiment,
    ExperimentResult,
)
_GOVERNANCE_KEYS = {
    "id",
    "project_id",
    "optimization_id",
    "status",
    "approval_status",
    "priority",
    "owner_user_id",
    "review_notes",
    "created_at",
    "updated_at",
}
_IMPACT_KEYS = {
    "id",
    "governance_id",
    "experiment_id",
    "status",
    "expected_impact",
    "actual_impact",
    "impact_score",
    "created_at",
    "updated_at",
}


def _svc() -> AIOptimizationGovernanceService:
    return AIOptimizationGovernanceService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id, account.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed_optimization(db: Session, pid: int, aid: int) -> int:
    opt = opt_repo.create_optimization(
        db, project_id=pid, account_id=aid, title="opt", optimization_score=60.0, priority="high"
    )
    return opt.id


def _protected_counts(db: Session) -> dict[str, int]:
    return {model.__name__: db.query(model).count() for model in _PROTECTED_MODELS}


def test_billing_governance_is_free() -> None:
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_GOVERNANCE_ANALYSIS] == 0
    assert costs[billing_service.USAGE_GOVERNANCE_REPORT] == 0


def test_cycle_records_no_usage_charge(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gsec_bill")
    _seed_optimization(db_session, pid, aid)
    before = db_session.query(UsageEvent).count()
    _svc().run_governance_cycle(db_session, pid, user_id=uid)
    assert db_session.query(UsageEvent).count() == before


def test_cycle_creates_no_business_objects(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gsec1")
    _seed_optimization(db_session, pid, aid)
    before = _protected_counts(db_session)
    _svc().run_governance_cycle(db_session, pid, user_id=uid)
    assert _protected_counts(db_session) == before


def test_analyze_does_not_auto_approve(db_session: Session) -> None:
    """analyze НЕ утверждает автоматически — все governance остаются pending."""
    pid, uid, aid = _project(db_session, "gsec2")
    _seed_optimization(db_session, pid, aid)
    out = _svc().run_governance_cycle(db_session, pid, user_id=uid)
    assert all(g["approval_status"] == "pending" for g in out["governances"])


def test_approve_does_not_mutate_business(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gsec3")
    _seed_optimization(db_session, pid, aid)
    svc = _svc()
    gid = svc.run_governance_cycle(db_session, pid, user_id=uid)["governances"][0]["id"]
    before = _protected_counts(db_session)
    svc.approve_optimization(db_session, gid, user_id=uid)
    assert _protected_counts(db_session) == before


def test_owner_fail_closed_cross_account(db_session: Session) -> None:
    """Назначить владельцем пользователя ЧУЖОГО аккаунта запрещено (FAIL CLOSED)."""
    pid_a, _uid_a, aid_a = _project(db_session, "gsec4a")
    _pid_b, uid_b, _aid_b = _project(db_session, "gsec4b")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid_a, account_id=aid_a, title="opt", optimization_score=60.0
    )
    governance = gov_repo.create_governance(
        db_session, project_id=pid_a, account_id=aid_a, optimization_id=opt.id
    )
    with pytest.raises(AIOptimizationGovernanceError):
        _svc().assign_owner(db_session, governance.id, uid_b)  # uid_b — из аккаунта B


def test_owner_fail_closed_on_check_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если сама проверка доступа падает — назначение отклоняется (FAIL CLOSED, не fail-open)."""
    pid, uid, aid = _project(db_session, "gsec4err")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    governance = gov_repo.create_governance(
        db_session, project_id=pid, account_id=aid, optimization_id=opt.id
    )

    def _boom(*_a: object, **_k: object) -> bool:
        raise RuntimeError("access check down")

    monkeypatch.setattr("app.services.saas_security_service.user_can_access_account", _boom)
    with pytest.raises(AIOptimizationGovernanceError):
        _svc().assign_owner(db_session, governance.id, uid)  # uid — валиден, но проверка падает
    db_session.refresh(governance)
    assert governance.owner_user_id is None  # владелец НЕ назначен


def test_owner_fail_closed_tenant_less(db_session: Session) -> None:
    """Governance без аккаунта (account_id=None) → назначение владельца отклоняется."""
    pid, uid, _aid = _project(db_session, "gsec4none")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=None, title="opt", optimization_score=60.0
    )
    governance = gov_repo.create_governance(
        db_session, project_id=pid, account_id=None, optimization_id=opt.id
    )
    with pytest.raises(AIOptimizationGovernanceError):
        _svc().assign_owner(db_session, governance.id, uid)


def test_analyze_does_not_run_or_mutate_experiments(db_session: Session) -> None:
    """Цикл governance НЕ создаёт эксперименты и НЕ меняет их статус (только читает)."""
    pid, uid, aid = _project(db_session, "gsec_exp")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    exp = opt_repo.create_experiment(
        db_session,
        optimization_id=opt.id,
        title="e",
        metric="m",
        baseline_value=50.0,
        target_value=60.0,
        status="draft",
    )
    before_count = db_session.query(OptimizationExperiment).count()
    _svc().run_governance_cycle(db_session, pid, user_id=uid)
    assert db_session.query(OptimizationExperiment).count() == before_count
    db_session.refresh(exp)
    assert exp.status == "draft"  # статус эксперимента не тронут


def test_no_secrets_in_views(db_session: Session) -> None:
    pid, uid, aid = _project(db_session, "gsec5")
    opt = opt_repo.create_optimization(
        db_session, project_id=pid, account_id=aid, title="opt", optimization_score=60.0
    )
    exp = opt_repo.create_experiment(
        db_session,
        optimization_id=opt.id,
        title="e",
        metric="m",
        baseline_value=50.0,
        target_value=60.0,
        status="completed",
    )
    opt_repo.create_result(
        db_session,
        experiment_id=exp.id,
        actual_value=65.0,
        expected_value=60.0,
        difference=5.0,
        validation_result="success",
        analysis={},
    )
    svc = _svc()
    out = svc.run_governance_cycle(db_session, pid, user_id=uid)
    detail = svc.get_governance_detail(db_session, out["governances"][0]["id"])
    blob = repr(out).lower() + repr(detail).lower()
    for hint in _SECRET_HINTS:
        assert hint not in blob
    assert set(out["governances"][0]) == _GOVERNANCE_KEYS
    assert set(detail["impacts"][0]) == _IMPACT_KEYS


def test_auth_required(client: TestClient, db_session: Session) -> None:
    pid, _, _ = _project(db_session, "gsec6")
    assert client.post(f"/projects/{pid}/optimization-governance").status_code == 401


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Гарды governance: чужой аккаунт НЕ получает чужие ресурсы (403/404)."""
    pid_a, uid_a, aid_a = _project(db_session, "gsec7a")
    _pid_b, uid_b, _aid_b = _project(db_session, "gsec7b")
    _seed_optimization(db_session, pid_a, aid_a)
    gid = client.post(
        f"/projects/{pid_a}/optimization-governance", headers=_h(uid_a), json={}
    ).json()["governances"][0]["id"]
    assert client.get(f"/governance/{gid}", headers=_h(uid_b)).status_code in (403, 404)
    assert client.post(f"/governance/{gid}/approve", headers=_h(uid_b), json={}).status_code in (
        403,
        404,
    )
    assert client.post(
        f"/projects/{pid_a}/optimization-governance", headers=_h(uid_b), json={}
    ).status_code in (403, 404)
