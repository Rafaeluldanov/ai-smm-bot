"""Репозиторий AI Autonomous Optimization (v0.8.1): оптимизации + эксперименты + результаты.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Optimization-слой: только оценивает, приоритизирует и проверяет улучшения; бизнес не меняет.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.experiment_result import ExperimentResult
from app.models.optimization_experiment import OptimizationExperiment
from app.models.optimization_item import OptimizationItem

# Поля, которые можно обновлять (whitelist).
_OPTIMIZATION_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "impact_score",
        "confidence_score",
        "cost_score",
        "risk_score",
        "optimization_score",
        "priority",
        "status",
    }
)
_EXPERIMENT_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "hypothesis",
        "metric",
        "baseline_value",
        "target_value",
        "status",
        "measurement_period",
    }
)

# Порядок приоритетов для сортировки (меньше = важнее).
_PRIORITY_ORDER: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


# ---------------------------------------------------------------------------- #
# Optimization items                                                           #
# ---------------------------------------------------------------------------- #


def create_optimization(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    title: str,
    improvement_id: int | None = None,
    description: str | None = None,
    impact_score: float = 0.0,
    confidence_score: float = 0.0,
    cost_score: float = 0.0,
    risk_score: float = 0.0,
    optimization_score: float = 0.0,
    priority: str = "medium",
    status: str = "identified",
) -> OptimizationItem:
    """Создать элемент оптимизации."""
    optimization = OptimizationItem(
        project_id=project_id,
        account_id=account_id,
        improvement_id=improvement_id,
        title=title[:255],
        description=description,
        impact_score=float(impact_score or 0.0),
        confidence_score=float(confidence_score or 0.0),
        cost_score=float(cost_score or 0.0),
        risk_score=float(risk_score or 0.0),
        optimization_score=float(optimization_score or 0.0),
        priority=priority,
        status=status,
    )
    db.add(optimization)
    db.commit()
    db.refresh(optimization)
    return optimization


def get_optimization(db: Session, optimization_id: int) -> OptimizationItem | None:
    """Оптимизация по id (или None)."""
    return db.get(OptimizationItem, optimization_id)


def list_optimizations(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[OptimizationItem]:
    """Оптимизации проекта, ранжированные (score убыв., свежие сверху)."""
    stmt = select(OptimizationItem).where(OptimizationItem.project_id == project_id)
    if status is not None:
        stmt = stmt.where(OptimizationItem.status == status)
    stmt = stmt.order_by(
        OptimizationItem.optimization_score.desc(), OptimizationItem.id.desc()
    ).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def list_optimizations_by_improvement(
    db: Session, project_id: int, improvement_id: int
) -> list[OptimizationItem]:
    """Оптимизации, созданные из конкретного улучшения (для идемпотентности)."""
    stmt = select(OptimizationItem).where(
        OptimizationItem.project_id == project_id,
        OptimizationItem.improvement_id == improvement_id,
    )
    return list(db.execute(stmt).scalars().all())


def update_optimization(
    db: Session, optimization: OptimizationItem, **fields: Any
) -> OptimizationItem:
    """Обновить поля оптимизации (только whitelist)."""
    for key, value in fields.items():
        if key in _OPTIMIZATION_FIELDS:
            setattr(optimization, key, value)
    db.commit()
    db.refresh(optimization)
    return optimization


def sort_by_priority(optimizations: list[OptimizationItem]) -> list[OptimizationItem]:
    """Отсортировать по приоритету (critical→low), при равенстве — по score убыв."""
    return sorted(
        optimizations,
        key=lambda o: (
            _PRIORITY_ORDER.get(o.priority, 99),
            -float(o.optimization_score or 0.0),
            -o.id,
        ),
    )


# ---------------------------------------------------------------------------- #
# Experiments                                                                  #
# ---------------------------------------------------------------------------- #


def create_experiment(
    db: Session,
    *,
    optimization_id: int,
    title: str,
    hypothesis: str | None = None,
    metric: str = "",
    baseline_value: float = 0.0,
    target_value: float = 0.0,
    status: str = "draft",
    measurement_period: int = 7,
) -> OptimizationExperiment:
    """Создать эксперимент оптимизации."""
    experiment = OptimizationExperiment(
        optimization_id=optimization_id,
        title=title[:255],
        hypothesis=hypothesis,
        metric=metric[:50],
        baseline_value=float(baseline_value or 0.0),
        target_value=float(target_value or 0.0),
        status=status,
        measurement_period=int(measurement_period or 0),
    )
    db.add(experiment)
    db.commit()
    db.refresh(experiment)
    return experiment


def get_experiment(db: Session, experiment_id: int) -> OptimizationExperiment | None:
    """Эксперимент по id (или None)."""
    return db.get(OptimizationExperiment, experiment_id)


def list_experiments(
    db: Session, optimization_id: int, *, limit: int = 200
) -> list[OptimizationExperiment]:
    """Эксперименты оптимизации (свежие сверху)."""
    stmt = (
        select(OptimizationExperiment)
        .where(OptimizationExperiment.optimization_id == optimization_id)
        .order_by(OptimizationExperiment.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def list_experiments_for_project(
    db: Session, project_id: int, *, limit: int = 200
) -> list[OptimizationExperiment]:
    """Эксперименты всего проекта (join через optimization_items), свежие сверху."""
    stmt = (
        select(OptimizationExperiment)
        .join(OptimizationItem, OptimizationExperiment.optimization_id == OptimizationItem.id)
        .where(OptimizationItem.project_id == project_id)
        .order_by(OptimizationExperiment.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_experiment(
    db: Session, experiment: OptimizationExperiment, **fields: Any
) -> OptimizationExperiment:
    """Обновить поля эксперимента (только whitelist)."""
    for key, value in fields.items():
        if key in _EXPERIMENT_FIELDS:
            setattr(experiment, key, value)
    db.commit()
    db.refresh(experiment)
    return experiment


# ---------------------------------------------------------------------------- #
# Experiment results                                                           #
# ---------------------------------------------------------------------------- #


def create_result(
    db: Session,
    *,
    experiment_id: int,
    actual_value: float,
    expected_value: float,
    difference: float,
    validation_result: str = "inconclusive",
    analysis: dict[str, Any] | None = None,
) -> ExperimentResult:
    """Создать результат эксперимента (append-only)."""
    result = ExperimentResult(
        experiment_id=experiment_id,
        actual_value=float(actual_value or 0.0),
        expected_value=float(expected_value or 0.0),
        difference=float(difference or 0.0),
        validation_result=validation_result,
        analysis=analysis or {},
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def get_latest_result(db: Session, experiment_id: int) -> ExperimentResult | None:
    """Последний результат эксперимента (или None)."""
    stmt = (
        select(ExperimentResult)
        .where(ExperimentResult.experiment_id == experiment_id)
        .order_by(ExperimentResult.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def list_results(db: Session, experiment_id: int, *, limit: int = 200) -> list[ExperimentResult]:
    """Результаты эксперимента (свежие сверху)."""
    stmt = (
        select(ExperimentResult)
        .where(ExperimentResult.experiment_id == experiment_id)
        .order_by(ExperimentResult.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_optimization_view(optimization: OptimizationItem) -> dict[str, Any]:
    """Безопасное представление оптимизации (без секретов)."""
    return {
        "id": optimization.id,
        "project_id": optimization.project_id,
        "improvement_id": optimization.improvement_id,
        "title": optimization.title,
        "description": optimization.description,
        "impact_score": round(float(optimization.impact_score or 0.0), 1),
        "confidence_score": round(float(optimization.confidence_score or 0.0), 1),
        "cost_score": round(float(optimization.cost_score or 0.0), 1),
        "risk_score": round(float(optimization.risk_score or 0.0), 1),
        "optimization_score": round(float(optimization.optimization_score or 0.0), 1),
        "priority": optimization.priority,
        "status": optimization.status,
        "created_at": optimization.created_at.isoformat() if optimization.created_at else None,
        "updated_at": optimization.updated_at.isoformat() if optimization.updated_at else None,
    }


def public_experiment_view(experiment: OptimizationExperiment) -> dict[str, Any]:
    """Безопасное представление эксперимента."""
    return {
        "id": experiment.id,
        "optimization_id": experiment.optimization_id,
        "title": experiment.title,
        "hypothesis": experiment.hypothesis,
        "metric": experiment.metric,
        "baseline_value": round(float(experiment.baseline_value or 0.0), 2),
        "target_value": round(float(experiment.target_value or 0.0), 2),
        "status": experiment.status,
        "measurement_period": experiment.measurement_period,
        "created_at": experiment.created_at.isoformat() if experiment.created_at else None,
        "updated_at": experiment.updated_at.isoformat() if experiment.updated_at else None,
    }


def public_result_view(result: ExperimentResult) -> dict[str, Any]:
    """Безопасное представление результата эксперимента."""
    return {
        "id": result.id,
        "experiment_id": result.experiment_id,
        "actual_value": round(float(result.actual_value or 0.0), 2),
        "expected_value": round(float(result.expected_value or 0.0), 2),
        "difference": round(float(result.difference or 0.0), 2),
        "validation_result": result.validation_result,
        "analysis": dict(result.analysis or {}),
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }


def build_optimization_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Optimization: счётчики/средний score через DB-агрегаты (без пагинационного среза)."""
    opt_where = OptimizationItem.project_id == project_id
    optimizations_total = db.execute(
        select(func.count()).select_from(OptimizationItem).where(opt_where)
    ).scalar_one()
    optimizations_open = db.execute(
        select(func.count())
        .select_from(OptimizationItem)
        .where(opt_where, OptimizationItem.status.in_(("identified", "planned", "running")))
    ).scalar_one()
    avg_score = db.execute(
        select(func.avg(OptimizationItem.optimization_score)).where(opt_where)
    ).scalar_one()
    exp_count = (
        select(func.count())
        .select_from(OptimizationExperiment)
        .join(OptimizationItem, OptimizationExperiment.optimization_id == OptimizationItem.id)
        .where(OptimizationItem.project_id == project_id)
    )
    experiments_total = db.execute(exp_count).scalar_one()
    experiments_completed = db.execute(
        exp_count.where(OptimizationExperiment.status == "completed")
    ).scalar_one()
    return {
        "project_id": project_id,
        "optimizations_total": int(optimizations_total or 0),
        "optimizations_open": int(optimizations_open or 0),
        "avg_optimization_score": round(float(avg_score or 0.0), 1),
        "experiments_total": int(experiments_total or 0),
        "experiments_completed": int(experiments_completed or 0),
    }
