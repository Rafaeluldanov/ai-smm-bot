"""Тесты безопасности AI Autonomous Optimization (v0.8.1, offline).

Инварианты (Part 17): optimization/аналитический слой — только оценивает, приоритизирует, проверяет.
Запрещено: применять улучшения; запускать эксперименты без подтверждения; менять бизнес/KPI/CRM/
бюджет; выполнять задачи; публиковать. Проверяем: billing 0 (config + поведение); цикл/валидация НЕ
создают бизнес-объектов; эксперимент стартует draft; секретов нет; tenant; crash-safety.
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
from app.models.post_publication import PostPublication
from app.models.quarter_objective import QuarterObjective
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import continuous_improvement_repository as ci_repo
from app.repositories import optimization_repository as repo
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_optimization_engine_service import AIOptimizationEngineService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")

# Бизнес-объекты, которые optimization-слой НЕ имеет права создавать/менять (Part 17).
_PROTECTED_MODELS = (
    PostPublication,
    BusinessWorkflow,
    ExecutionPlan,
    ExecutionTask,
    BusinessObjective,
    QuarterObjective,
    CrmSmmResource,
)

# Разрешённый набор ключей публичных представлений (защита от over-exposure).
_OPTIMIZATION_KEYS = {
    "id",
    "project_id",
    "improvement_id",
    "title",
    "description",
    "impact_score",
    "confidence_score",
    "cost_score",
    "risk_score",
    "optimization_score",
    "priority",
    "status",
    "created_at",
    "updated_at",
}
_EXPERIMENT_KEYS = {
    "id",
    "optimization_id",
    "title",
    "hypothesis",
    "metric",
    "baseline_value",
    "target_value",
    "status",
    "measurement_period",
    "created_at",
    "updated_at",
}


def _svc() -> AIOptimizationEngineService:
    return AIOptimizationEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed_improvement(db: Session, pid: int) -> None:
    ci_repo.create_improvement(
        db,
        project_id=pid,
        account_id=None,
        title="Снять блокеры",
        priority="high",
        description="уменьшить зависимости",
    )


def _protected_counts(db: Session) -> dict[str, int]:
    return {model.__name__: db.query(model).count() for model in _PROTECTED_MODELS}


def test_billing_optimization_is_free() -> None:
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_OPTIMIZATION_ANALYSIS] == 0
    assert costs[billing_service.USAGE_OPTIMIZATION_REPORT] == 0


def test_cycle_records_no_usage_charge(db_session: Session) -> None:
    """Поведенческая проверка «бесплатно»: цикл НЕ создаёт списаний (UsageEvent)."""
    pid, uid = _project(db_session, "osec_bill")
    _seed_improvement(db_session, pid)
    before = db_session.query(UsageEvent).count()
    _svc().run_optimization_cycle(db_session, pid, user_id=uid)
    assert db_session.query(UsageEvent).count() == before


def test_cycle_creates_no_business_objects(db_session: Session) -> None:
    """Цикл оптимизации НЕ создаёт/меняет бизнес-объекты (KPI/CRM/задачи/публикации)."""
    pid, uid = _project(db_session, "osec1")
    _seed_improvement(db_session, pid)
    before = _protected_counts(db_session)
    _svc().run_optimization_cycle(db_session, pid, user_id=uid)
    assert _protected_counts(db_session) == before


def test_experiment_starts_as_draft(db_session: Session) -> None:
    """Эксперимент создаётся как ЧЕРНОВИК (draft) — не запускается автоматически."""
    pid, uid = _project(db_session, "osec2")
    _seed_improvement(db_session, pid)
    svc = _svc()
    opt = svc.run_optimization_cycle(db_session, pid, user_id=uid)["optimizations"][0]
    exp = svc.create_experiment(db_session, opt["id"], user_id=uid)
    assert exp["status"] == "draft"  # НЕ running


def test_validate_does_not_mutate_business(db_session: Session) -> None:
    """Валидация эксперимента НЕ меняет бизнес-объекты."""
    pid, uid = _project(db_session, "osec3")
    _seed_improvement(db_session, pid)
    svc = _svc()
    opt = svc.run_optimization_cycle(db_session, pid, user_id=uid)["optimizations"][0]
    exp = svc.create_experiment(db_session, opt["id"], user_id=uid)
    before = _protected_counts(db_session)
    svc.validate_experiment(
        db_session, exp["id"], actual_value=exp["target_value"] + 5, user_id=uid
    )
    assert _protected_counts(db_session) == before


def test_no_secrets_in_views(db_session: Session) -> None:
    """Публичные представления без секретов И без over-exposure внутренних полей."""
    pid, _ = _project(db_session, "osec4")
    _seed_improvement(db_session, pid)
    svc = _svc()
    out = svc.run_optimization_cycle(db_session, pid)
    exp = svc.create_experiment(db_session, out["optimizations"][0]["id"])
    blob = repr(out).lower() + repr(exp).lower()
    for hint in _SECRET_HINTS:
        assert hint not in blob
    assert set(out["optimizations"][0]) == _OPTIMIZATION_KEYS
    assert set(exp) == _EXPERIMENT_KEYS


def test_auth_required(client: TestClient, db_session: Session) -> None:
    pid, _ = _project(db_session, "osec5")
    assert client.post(f"/projects/{pid}/optimization/analyze").status_code == 401


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Владелец другого аккаунта не видит чужой проект (guard → 403/404)."""
    pid_a, _ = _project(db_session, "osec6a")
    _pid_b, uid_b = _project(db_session, "osec6b")
    resp = client.post(f"/projects/{pid_a}/optimization/analyze", headers=_h(uid_b))
    assert resp.status_code in (403, 404)


def test_crash_safety_adjacent_layers(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Падение смежных слоёв не роняет оценку (read-only try/except)."""
    pid, uid = _project(db_session, "osec7")
    # Улучшение СВЯЗАНО с паттерном → _derive_confidence реально зовёт ci_repo.get_pattern (_boom).
    pattern = ci_repo.create_pattern(
        db_session,
        project_id=pid,
        account_id=None,
        pattern_type="failure_pattern",
        title="p",
        confidence_score=80.0,
    )
    ci_repo.create_improvement(
        db_session,
        project_id=pid,
        account_id=None,
        pattern_id=pattern.id,
        title="Снять блокеры",
        priority="high",
        description="уменьшить зависимости",
    )

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("adjacent layer down")

    from app.repositories import execution_repository as exec_repo
    from app.repositories import performance_repository as perf_repo

    monkeypatch.setattr(perf_repo, "get_latest_snapshot", _boom)
    monkeypatch.setattr(exec_repo, "list_execution_plans", _boom)
    monkeypatch.setattr(ci_repo, "get_pattern", _boom)  # теперь реально срабатывает

    out = _svc().run_optimization_cycle(db_session, pid, user_id=uid)  # не падает
    assert len(out["created"]) == 1  # оптимизация всё равно оценена (fallback-оценки)
    assert repo.list_optimizations(db_session, pid)


def test_backlog_read_failure_degrades_gracefully(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Падение чтения Improvement Backlog (ci_repo.list_improvements) не роняет цикл (HIGH-фикс)."""
    pid, uid = _project(db_session, "osec8")
    _seed_improvement(db_session, pid)

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("backlog down")

    monkeypatch.setattr(ci_repo, "list_improvements", _boom)
    out = _svc().run_optimization_cycle(db_session, pid, user_id=uid)  # не падает
    assert out["created"] == []  # backlog недоступен → пустой цикл, без исключения


def test_tenant_isolation_optimization_and_experiment(
    client: TestClient, db_session: Session
) -> None:
    """Гарды optimization/experiment: чужой аккаунт НЕ получает чужие ресурсы (403/404)."""
    pid_a, uid_a = _project(db_session, "osec9a")
    _pid_b, uid_b = _project(db_session, "osec9b")
    _seed_improvement(db_session, pid_a)
    opt = client.post(f"/projects/{pid_a}/optimization/analyze", headers=_h(uid_a), json={}).json()[
        "optimizations"
    ][0]
    exp = client.post(f"/optimizations/{opt['id']}/experiment", headers=_h(uid_a), json={}).json()
    # Пользователь аккаунта B пытается достать ресурсы аккаунта A.
    assert client.get(f"/optimizations/{opt['id']}", headers=_h(uid_b)).status_code in (403, 404)
    assert client.post(
        f"/optimizations/{opt['id']}/experiment", headers=_h(uid_b), json={}
    ).status_code in (403, 404)
    assert client.get(f"/optimization-experiments/{exp['id']}", headers=_h(uid_b)).status_code in (
        403,
        404,
    )
    assert client.post(
        f"/optimization-experiments/{exp['id']}/validate",
        headers=_h(uid_b),
        json={"actual_value": 1},
    ).status_code in (403, 404)
