"""Тесты экспериментов и валидации — AI Autonomous Optimization (v0.8.1, offline).

Инварианты:
- create_experiment создаёт ЧЕРНОВИК (draft, не запускается); evaluate/validate_result корректны
  для обоих направлений метрики; validate_experiment завершает и создаёт feedback; аудит.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import optimization_repository as repo
from app.schemas.project import ProjectCreate
from app.services.ai_optimization_engine_service import (
    AIOptimizationEngineError,
    AIOptimizationEngineService,
)

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIOptimizationEngineService:
    return AIOptimizationEngineService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id, owner.id


def _optimization(db: Session, pid: int, *, title: str = "Ускорить исполнение") -> int:
    opt = repo.create_optimization(
        db, project_id=pid, account_id=None, title=title, optimization_score=40.0, priority="medium"
    )
    return opt.id


def _experiment(db: Session, *, baseline: float, target: float):
    pid, _ = _project(db, f"exq{int(baseline)}{int(target)}")
    oid = _optimization(db, pid)
    return repo.create_experiment(
        db, optimization_id=oid, title="e", metric="m", baseline_value=baseline, target_value=target
    )


def test_create_experiment_draft(db_session: Session) -> None:
    pid, uid = _project(db_session, "exp1")
    oid = _optimization(db_session, pid, title="Снять зависимости исполнения")
    exp = _svc().create_experiment(db_session, oid, user_id=uid)
    assert exp["status"] == "draft"  # НЕ запускается автоматически
    assert exp["metric"] == "execution_speed"
    assert exp["target_value"] >= exp["baseline_value"]
    opt = repo.get_optimization(db_session, oid)
    assert opt is not None and opt.status == "planned"


def test_evaluate_experiment(db_session: Session) -> None:
    exp = _experiment(db_session, baseline=50.0, target=60.0)
    ev = _svc().evaluate_experiment(exp, 62.0)
    assert ev["expected"] == 60.0 and ev["difference"] == 2.0
    assert ev["analysis"]["vs_baseline"] == 12.0


def test_validate_result_success_up(db_session: Session) -> None:
    exp = _experiment(db_session, baseline=50.0, target=60.0)
    assert _svc().validate_result(exp, 60.0) == "success"
    assert _svc().validate_result(exp, 65.0) == "success"


def test_validate_result_failure_up(db_session: Session) -> None:
    exp = _experiment(db_session, baseline=50.0, target=60.0)
    assert _svc().validate_result(exp, 50.0) == "failure"
    assert _svc().validate_result(exp, 45.0) == "failure"


def test_validate_result_inconclusive(db_session: Session) -> None:
    exp = _experiment(db_session, baseline=50.0, target=60.0)
    assert _svc().validate_result(exp, 55.0) == "inconclusive"


def test_validate_result_lower_is_better(db_session: Session) -> None:
    """Метрика «меньше = лучше» (target < baseline)."""
    exp = _experiment(db_session, baseline=10.0, target=4.0)
    assert _svc().validate_result(exp, 4.0) == "success"
    assert _svc().validate_result(exp, 10.0) == "failure"
    assert _svc().validate_result(exp, 7.0) == "inconclusive"


def test_validate_result_target_equals_baseline(db_session: Session) -> None:
    exp = _experiment(db_session, baseline=50.0, target=50.0)
    assert _svc().validate_result(exp, 99.0) == "inconclusive"


def test_validate_experiment_flow(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "expf")
    oid = _optimization(db_session, pid)
    svc = _svc()
    exp = svc.create_experiment(
        db_session, oid, user_id=uid, baseline_value=50.0, target_value=60.0
    )
    out = svc.validate_experiment(db_session, exp["id"], actual_value=65.0, user_id=uid)
    assert out["validation"] == "success"
    assert out["experiment"]["status"] == "completed"
    assert out["result"]["validation_result"] == "success"
    opt = repo.get_optimization(db_session, oid)
    assert opt is not None and opt.status == "completed"
    actions = {e.action for e in db_session.query(AuditLogEntry).filter_by(project_id=pid).all()}
    assert "optimization.experiment_completed" in actions
    assert "optimization.experiment_validated" in actions


def test_revalidate_completed_raises(db_session: Session) -> None:
    """Повторная валидация завершённого эксперимента запрещена (нет дублей результата/feedback)."""
    from app.models.audit_log import AuditLogEntry

    pid, uid = _project(db_session, "expr")
    oid = _optimization(db_session, pid)
    svc = _svc()
    exp = svc.create_experiment(
        db_session, oid, user_id=uid, baseline_value=50.0, target_value=60.0
    )
    svc.validate_experiment(db_session, exp["id"], actual_value=65.0, user_id=uid)
    results_before = len(repo.list_results(db_session, exp["id"]))
    validated_before = (
        db_session.query(AuditLogEntry)
        .filter_by(project_id=pid, action="optimization.experiment_validated")
        .count()
    )
    with pytest.raises(AIOptimizationEngineError):
        svc.validate_experiment(db_session, exp["id"], actual_value=70.0, user_id=uid)
    # ни результат, ни audit не продублированы.
    assert len(repo.list_results(db_session, exp["id"])) == results_before
    assert (
        db_session.query(AuditLogEntry)
        .filter_by(project_id=pid, action="optimization.experiment_validated")
        .count()
        == validated_before
    )


def test_experiment_does_not_regress_completed_optimization(db_session: Session) -> None:
    """create_experiment НЕ регрессирует completed-оптимизацию обратно в planned."""
    pid, uid = _project(db_session, "expreg")
    oid = _optimization(db_session, pid)
    svc = _svc()
    exp = svc.create_experiment(
        db_session, oid, user_id=uid, baseline_value=50.0, target_value=60.0
    )
    svc.validate_experiment(db_session, exp["id"], actual_value=65.0, user_id=uid)
    assert repo.get_optimization(db_session, oid).status == "completed"
    svc.create_experiment(db_session, oid, user_id=uid, baseline_value=50.0, target_value=70.0)
    assert repo.get_optimization(db_session, oid).status == "completed"  # НЕ planned
