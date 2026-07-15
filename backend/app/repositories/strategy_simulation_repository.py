"""Репозиторий AI Strategy Simulator (v0.7.5): симуляции + прогнозы + сравнения.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Прогноз — модельная оценка, НЕ финансовая гарантия.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.forecast_result import ForecastResult
from app.models.scenario_comparison import ScenarioComparison
from app.models.strategy_simulation import StrategySimulation

# Поля симуляции, которые можно обновлять (whitelist).
_SIMULATION_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "title",
        "objective",
        "assumptions",
        "simulation_period",
        "confidence_level",
        "overall_score",
    }
)


# ---------------------------------------------------------------------------- #
# Simulations                                                                  #
# ---------------------------------------------------------------------------- #


def create_simulation(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    scenario_id: int,
    title: str,
    decision_id: int | None = None,
    objective: str | None = None,
    assumptions: list[Any] | None = None,
    simulation_period: str = "90_days",
    confidence_level: str = "medium",
    status: str = "generated",
    overall_score: float = 0.0,
) -> StrategySimulation:
    """Создать стратегическую симуляцию (status=generated по умолчанию)."""
    simulation = StrategySimulation(
        project_id=project_id,
        account_id=account_id,
        decision_id=decision_id,
        scenario_id=scenario_id,
        title=title[:255],
        objective=objective,
        assumptions=assumptions or [],
        simulation_period=simulation_period,
        confidence_level=confidence_level,
        status=status,
        overall_score=float(overall_score or 0.0),
    )
    db.add(simulation)
    db.commit()
    db.refresh(simulation)
    return simulation


def get_simulation(db: Session, simulation_id: int) -> StrategySimulation | None:
    """Симуляция по id (или None)."""
    return db.get(StrategySimulation, simulation_id)


def list_simulations(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[StrategySimulation]:
    """Симуляции проекта (свежие сверху), опционально по статусу."""
    stmt = select(StrategySimulation).where(StrategySimulation.project_id == project_id)
    if status is not None:
        stmt = stmt.where(StrategySimulation.status == status)
    stmt = stmt.order_by(StrategySimulation.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_simulation(
    db: Session, simulation: StrategySimulation, **fields: Any
) -> StrategySimulation:
    """Обновить поля симуляции (только whitelist)."""
    for key, value in fields.items():
        if key in _SIMULATION_FIELDS:
            setattr(simulation, key, value)
    db.commit()
    db.refresh(simulation)
    return simulation


# ---------------------------------------------------------------------------- #
# Forecasts                                                                     #
# ---------------------------------------------------------------------------- #


def create_forecast(
    db: Session,
    *,
    simulation_id: int,
    metric: str,
    period: str,
    baseline_value: float = 0.0,
    forecast_value: float = 0.0,
    change_percent: float = 0.0,
    confidence_score: float = 0.0,
    reasoning: list[Any] | None = None,
) -> ForecastResult:
    """Создать прогноз метрики (append-only)."""
    forecast = ForecastResult(
        simulation_id=simulation_id,
        metric=metric,
        period=period,
        baseline_value=float(baseline_value or 0.0),
        forecast_value=float(forecast_value or 0.0),
        change_percent=float(change_percent or 0.0),
        confidence_score=float(confidence_score or 0.0),
        reasoning=reasoning or [],
    )
    db.add(forecast)
    db.commit()
    db.refresh(forecast)
    return forecast


def delete_forecasts(db: Session, simulation_id: int) -> None:
    """Удалить прогнозы симуляции (пересчёт при повторном run)."""
    db.query(ForecastResult).filter(ForecastResult.simulation_id == simulation_id).delete(
        synchronize_session=False
    )
    db.commit()


def list_forecasts(db: Session, simulation_id: int, *, limit: int = 500) -> list[ForecastResult]:
    """Прогнозы симуляции (по порядку создания)."""
    stmt = (
        select(ForecastResult)
        .where(ForecastResult.simulation_id == simulation_id)
        .order_by(ForecastResult.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Comparisons                                                                   #
# ---------------------------------------------------------------------------- #


def create_comparison(
    db: Session,
    *,
    decision_id: int,
    winner_scenario_id: int | None = None,
    comparison_data: dict[str, Any] | None = None,
    score_difference: float = 0.0,
    reasoning: list[Any] | None = None,
) -> ScenarioComparison:
    """Создать сравнение сценариев (append-only)."""
    comparison = ScenarioComparison(
        decision_id=decision_id,
        winner_scenario_id=winner_scenario_id,
        comparison_data=comparison_data or {},
        score_difference=float(score_difference or 0.0),
        reasoning=reasoning or [],
    )
    db.add(comparison)
    db.commit()
    db.refresh(comparison)
    return comparison


def get_scenario_comparison(db: Session, decision_id: int) -> ScenarioComparison | None:
    """Последнее сравнение сценариев решения (свежее сверху) или None."""
    stmt = (
        select(ScenarioComparison)
        .where(ScenarioComparison.decision_id == decision_id)
        .order_by(ScenarioComparison.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def list_comparisons(
    db: Session, decision_id: int, *, limit: int = 100
) -> list[ScenarioComparison]:
    """История сравнений решения (свежие сверху)."""
    stmt = (
        select(ScenarioComparison)
        .where(ScenarioComparison.decision_id == decision_id)
        .order_by(ScenarioComparison.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_simulation_view(simulation: StrategySimulation) -> dict[str, Any]:
    """Безопасное представление симуляции (без секретов)."""
    return {
        "id": simulation.id,
        "project_id": simulation.project_id,
        "decision_id": simulation.decision_id,
        "scenario_id": simulation.scenario_id,
        "status": simulation.status,
        "title": simulation.title,
        "objective": simulation.objective,
        "assumptions": list(simulation.assumptions or []),
        "simulation_period": simulation.simulation_period,
        "confidence_level": simulation.confidence_level,
        "overall_score": round(float(simulation.overall_score or 0.0), 1),
        "created_at": simulation.created_at.isoformat() if simulation.created_at else None,
        "updated_at": simulation.updated_at.isoformat() if simulation.updated_at else None,
    }


def public_forecast_view(forecast: ForecastResult) -> dict[str, Any]:
    """Безопасное представление прогноза (модельная оценка, не гарантия)."""
    return {
        "id": forecast.id,
        "simulation_id": forecast.simulation_id,
        "metric": forecast.metric,
        "period": forecast.period,
        "baseline_value": round(float(forecast.baseline_value or 0.0), 2),
        "forecast_value": round(float(forecast.forecast_value or 0.0), 2),
        "change_percent": round(float(forecast.change_percent or 0.0), 1),
        "confidence_score": round(float(forecast.confidence_score or 0.0), 1),
        "reasoning": list(forecast.reasoning or []),
        "created_at": forecast.created_at.isoformat() if forecast.created_at else None,
    }


def public_comparison_view(comparison: ScenarioComparison) -> dict[str, Any]:
    """Безопасное представление сравнения сценариев."""
    return {
        "id": comparison.id,
        "decision_id": comparison.decision_id,
        "winner_scenario_id": comparison.winner_scenario_id,
        "comparison_data": dict(comparison.comparison_data or {}),
        "score_difference": round(float(comparison.score_difference or 0.0), 1),
        "reasoning": list(comparison.reasoning or []),
        "created_at": comparison.created_at.isoformat() if comparison.created_at else None,
    }


def build_simulation_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Strategy Simulator: счётчики симуляций по ключевым статусам."""
    simulations = list_simulations(db, project_id)
    open_count = sum(1 for s in simulations if s.status in ("generated", "running"))
    completed = sum(1 for s in simulations if s.status in ("completed", "reviewed"))
    return {
        "project_id": project_id,
        "simulations_total": len(simulations),
        "simulations_open": open_count,
        "simulations_completed": completed,
    }
