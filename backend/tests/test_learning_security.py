"""Тесты безопасности AI Continuous Improvement (v0.8.0, offline).

Инварианты (Part 18): learning/analytical слой — только учится и советует.
Запрещено: применять улучшения; менять стратегию/KPI/CRM/бюджет; выполнять задачи; публиковать.
Проверяем: billing 0; цикл ничего не публикует/не создаёт бизнес-объекты; approve НЕ применяет;
секретов в ответах нет; tenant isolation (auth + cross-tenant); crash-safety смежных слоёв.
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
from app.repositories import performance_repository as perf_repo
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_continuous_improvement_service import AIContinuousImprovementService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")

# Бизнес-объекты, которые learning-слой НЕ имеет права создавать/менять (Part 18).
_PROTECTED_MODELS = (
    PostPublication,  # публикации
    BusinessWorkflow,  # бизнес-процессы
    ExecutionPlan,  # планы исполнения
    ExecutionTask,  # выполнение задач
    BusinessObjective,  # стратегия/KPI
    QuarterObjective,  # квартальные цели/KPI
    CrmSmmResource,  # CRM
)

# Разрешённый набор ключей публичных представлений (защита от over-exposure).
_EXPERIENCE_KEYS = {
    "id",
    "project_id",
    "experience_type",
    "source_id",
    "title",
    "context",
    "expected_result",
    "actual_result",
    "outcome",
    "lessons",
    "confidence_score",
    "created_at",
    "updated_at",
}
_IMPROVEMENT_KEYS = {
    "id",
    "project_id",
    "pattern_id",
    "status",
    "priority",
    "title",
    "description",
    "expected_impact",
    "created_at",
    "updated_at",
}


def _protected_counts(db: Session) -> dict[str, int]:
    """Снимок числа строк во всех защищённых бизнес-таблицах."""
    return {model.__name__: db.query(model).count() for model in _PROTECTED_MODELS}


def _svc() -> AIContinuousImprovementService:
    return AIContinuousImprovementService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _seed_failing(db: Session, pid: int) -> None:
    snap = perf_repo.create_snapshot(
        db,
        project_id=pid,
        account_id=None,
        status="critical",
        performance_score=25.0,
        target_state={"revenue": 1000},
        actual_state={"revenue": 300},
    )
    perf_repo.create_deviation(
        db, snapshot_id=snap.id, metric="revenue", title="revenue -70%", impact="critical"
    )


def test_billing_learning_is_free() -> None:
    """Config-guard: тарифы learning-действий = 0 units."""
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_LEARNING_ANALYSIS] == 0
    assert costs[billing_service.USAGE_LEARNING_REPORT] == 0


def test_cycle_records_no_usage_charge(db_session: Session) -> None:
    """Поведенческая проверка «бесплатно»: цикл НЕ создаёт списаний (UsageEvent)."""
    pid, uid = _project(db_session, "sec_bill")
    _seed_failing(db_session, pid)
    before = db_session.query(UsageEvent).count()
    _svc().run_learning_cycle(db_session, pid, user_id=uid)
    assert db_session.query(UsageEvent).count() == before  # ни одного списания


def test_cycle_creates_no_business_objects(db_session: Session) -> None:
    """Цикл обучения НЕ публикует и НЕ создаёт/меняет бизнес-объекты (KPI/CRM/задачи/…)."""
    pid, uid = _project(db_session, "sec1")
    _seed_failing(db_session, pid)
    before = _protected_counts(db_session)
    _svc().run_learning_cycle(db_session, pid, user_id=uid)
    assert _protected_counts(db_session) == before


def test_approve_does_not_apply(db_session: Session) -> None:
    """approve меняет ТОЛЬКО статус — не создаёт задач/публикаций/бизнес-объектов."""
    pid, uid = _project(db_session, "sec2")
    _seed_failing(db_session, pid)
    improvements = _svc().run_learning_cycle(db_session, pid, user_id=uid)["improvements"]
    before = _protected_counts(db_session)
    out = _svc().approve_improvement(db_session, improvements[0]["id"], user_id=uid)
    assert out["status"] == "accepted"
    assert _protected_counts(db_session) == before


def test_no_secrets_in_views(db_session: Session) -> None:
    """Публичные представления не протекают секретов И не переэкспонируют внутренние поля."""
    pid, _ = _project(db_session, "sec3")
    _seed_failing(db_session, pid)
    svc = _svc()
    out = svc.run_learning_cycle(db_session, pid)
    history = svc.get_history(db_session, pid)
    # 1) явных секретов нет.
    blob = repr(out).lower() + repr(history).lower()
    for hint in _SECRET_HINTS:
        assert hint not in blob
    # 2) структурный allowlist — ловит over-exposure (напр. public_view → __dict__).
    assert set(history["experiences"][0]) == _EXPERIENCE_KEYS
    assert set(out["improvements"][0]) == _IMPROVEMENT_KEYS


def test_auth_required(client: TestClient, db_session: Session) -> None:
    pid, _ = _project(db_session, "sec4")
    assert client.post(f"/projects/{pid}/improvement/analyze").status_code == 401


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Владелец другого аккаунта не видит чужой проект (guard → 403/404)."""
    pid_a, _ = _project(db_session, "sec5a")
    _pid_b, uid_b = _project(db_session, "sec5b")
    resp = client.post(f"/projects/{pid_a}/improvement/analyze", headers=_h(uid_b))
    assert resp.status_code in (403, 404)


def test_crash_safety_adjacent_layers(db_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Если смежные слои падают при чтении — цикл выживает (read-only try/except)."""
    pid, uid = _project(db_session, "sec6")
    _seed_failing(db_session, pid)

    def _boom(*_a: object, **_k: object) -> object:
        raise RuntimeError("adjacent layer down")

    from app.repositories import (
        business_forecast_repository as fc_repo,
    )
    from app.repositories import (
        decision_repository as decision_repo,
    )
    from app.repositories import (
        execution_repository as exec_repo,
    )

    monkeypatch.setattr(perf_repo, "get_latest_snapshot", _boom)
    monkeypatch.setattr(exec_repo, "list_execution_plans", _boom)
    monkeypatch.setattr(decision_repo, "list_decisions", _boom)
    monkeypatch.setattr(fc_repo, "get_latest_forecast", _boom)

    out = _svc().run_learning_cycle(db_session, pid, user_id=uid)  # не падает
    assert out["experiences"] == [] and out["insights"]
