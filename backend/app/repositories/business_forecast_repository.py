"""Репозиторий AI Business Forecasting Engine (v0.7.6): прогнозы + метрики + roadmap.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Прогноз — модельная оценка, НЕ финансовая гарантия.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.business_forecast import BusinessForecast
from app.models.business_roadmap import BusinessRoadmap
from app.models.forecast_metric import ForecastMetric

# Поля прогноза, которые можно обновлять (whitelist).
_FORECAST_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "horizon",
        "title",
        "baseline_state",
        "forecast_state",
        "assumptions",
        "risk_level",
        "confidence_score",
        "generated_at",
    }
)


# ---------------------------------------------------------------------------- #
# Forecasts                                                                    #
# ---------------------------------------------------------------------------- #


def create_forecast(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    title: str,
    horizon: str = "12_months",
    status: str = "generated",
    baseline_state: dict[str, Any] | None = None,
    forecast_state: dict[str, Any] | None = None,
    assumptions: list[Any] | None = None,
    risk_level: str = "medium",
    confidence_score: float = 0.0,
) -> BusinessForecast:
    """Создать прогноз развития бизнеса (status=generated по умолчанию)."""
    forecast = BusinessForecast(
        project_id=project_id,
        account_id=account_id,
        title=title[:255],
        horizon=horizon,
        status=status,
        baseline_state=baseline_state or {},
        forecast_state=forecast_state or {},
        assumptions=assumptions or [],
        risk_level=risk_level,
        confidence_score=float(confidence_score or 0.0),
    )
    db.add(forecast)
    db.commit()
    db.refresh(forecast)
    return forecast


def get_forecast(db: Session, forecast_id: int) -> BusinessForecast | None:
    """Прогноз по id (или None)."""
    return db.get(BusinessForecast, forecast_id)


def list_forecasts(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[BusinessForecast]:
    """Прогнозы проекта (свежие сверху), опционально по статусу."""
    stmt = select(BusinessForecast).where(BusinessForecast.project_id == project_id)
    if status is not None:
        stmt = stmt.where(BusinessForecast.status == status)
    stmt = stmt.order_by(BusinessForecast.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def get_latest_forecast(db: Session, project_id: int) -> BusinessForecast | None:
    """Последний прогноз проекта (свежий сверху) или None."""
    stmt = (
        select(BusinessForecast)
        .where(BusinessForecast.project_id == project_id)
        .order_by(BusinessForecast.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def update_forecast(db: Session, forecast: BusinessForecast, **fields: Any) -> BusinessForecast:
    """Обновить поля прогноза (только whitelist)."""
    for key, value in fields.items():
        if key in _FORECAST_FIELDS:
            setattr(forecast, key, value)
    db.commit()
    db.refresh(forecast)
    return forecast


# ---------------------------------------------------------------------------- #
# Metrics                                                                       #
# ---------------------------------------------------------------------------- #


def create_metric(
    db: Session,
    *,
    forecast_id: int,
    metric: str,
    baseline_value: float = 0.0,
    forecast_value: float = 0.0,
    change_percent: float = 0.0,
    confidence_score: float = 0.0,
    reasoning: list[Any] | None = None,
) -> ForecastMetric:
    """Создать KPI-проекцию метрики (append-only)."""
    row = ForecastMetric(
        forecast_id=forecast_id,
        metric=metric,
        baseline_value=float(baseline_value or 0.0),
        forecast_value=float(forecast_value or 0.0),
        change_percent=float(change_percent or 0.0),
        confidence_score=float(confidence_score or 0.0),
        reasoning=reasoning or [],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_metrics(db: Session, forecast_id: int) -> None:
    """Удалить метрики прогноза (пересчёт при повторной генерации)."""
    db.query(ForecastMetric).filter(ForecastMetric.forecast_id == forecast_id).delete(
        synchronize_session=False
    )
    db.commit()


def list_metrics(db: Session, forecast_id: int, *, limit: int = 500) -> list[ForecastMetric]:
    """Метрики прогноза (по порядку создания)."""
    stmt = (
        select(ForecastMetric)
        .where(ForecastMetric.forecast_id == forecast_id)
        .order_by(ForecastMetric.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Roadmaps                                                                       #
# ---------------------------------------------------------------------------- #


def create_roadmap(
    db: Session,
    *,
    forecast_id: int,
    title: str,
    quarters: list[Any] | None = None,
    milestones: list[Any] | None = None,
    risks: list[Any] | None = None,
    recommendations: list[Any] | None = None,
) -> BusinessRoadmap:
    """Создать квартальный roadmap прогноза."""
    roadmap = BusinessRoadmap(
        forecast_id=forecast_id,
        title=title[:255],
        quarters=quarters or [],
        milestones=milestones or [],
        risks=risks or [],
        recommendations=recommendations or [],
    )
    db.add(roadmap)
    db.commit()
    db.refresh(roadmap)
    return roadmap


def delete_roadmaps(db: Session, forecast_id: int) -> None:
    """Удалить roadmap прогноза (пересоздание при повторной генерации)."""
    db.query(BusinessRoadmap).filter(BusinessRoadmap.forecast_id == forecast_id).delete(
        synchronize_session=False
    )
    db.commit()


def get_roadmap(db: Session, forecast_id: int) -> BusinessRoadmap | None:
    """Последний roadmap прогноза (свежий сверху) или None."""
    stmt = (
        select(BusinessRoadmap)
        .where(BusinessRoadmap.forecast_id == forecast_id)
        .order_by(BusinessRoadmap.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_forecast_view(forecast: BusinessForecast) -> dict[str, Any]:
    """Безопасное представление прогноза (без секретов)."""
    return {
        "id": forecast.id,
        "project_id": forecast.project_id,
        "status": forecast.status,
        "horizon": forecast.horizon,
        "title": forecast.title,
        "baseline_state": dict(forecast.baseline_state or {}),
        "forecast_state": dict(forecast.forecast_state or {}),
        "assumptions": list(forecast.assumptions or []),
        "risk_level": forecast.risk_level,
        "confidence_score": round(float(forecast.confidence_score or 0.0), 1),
        "generated_at": forecast.generated_at.isoformat() if forecast.generated_at else None,
        "created_at": forecast.created_at.isoformat() if forecast.created_at else None,
        "updated_at": forecast.updated_at.isoformat() if forecast.updated_at else None,
    }


def public_metric_view(metric: ForecastMetric) -> dict[str, Any]:
    """Безопасное представление KPI-проекции (модельная оценка, не гарантия)."""
    return {
        "id": metric.id,
        "forecast_id": metric.forecast_id,
        "metric": metric.metric,
        "baseline_value": round(float(metric.baseline_value or 0.0), 2),
        "forecast_value": round(float(metric.forecast_value or 0.0), 2),
        "change_percent": round(float(metric.change_percent or 0.0), 1),
        "confidence_score": round(float(metric.confidence_score or 0.0), 1),
        "reasoning": list(metric.reasoning or []),
        "created_at": metric.created_at.isoformat() if metric.created_at else None,
    }


def public_roadmap_view(roadmap: BusinessRoadmap) -> dict[str, Any]:
    """Безопасное представление roadmap."""
    return {
        "id": roadmap.id,
        "forecast_id": roadmap.forecast_id,
        "title": roadmap.title,
        "quarters": list(roadmap.quarters or []),
        "milestones": list(roadmap.milestones or []),
        "risks": list(roadmap.risks or []),
        "recommendations": list(roadmap.recommendations or []),
        "created_at": roadmap.created_at.isoformat() if roadmap.created_at else None,
        "updated_at": roadmap.updated_at.isoformat() if roadmap.updated_at else None,
    }


def build_forecast_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Business Forecasting: счётчики прогнозов по ключевым статусам."""
    forecasts = list_forecasts(db, project_id)
    generated = sum(1 for f in forecasts if f.status == "generated")
    reviewed = sum(1 for f in forecasts if f.status == "reviewed")
    return {
        "project_id": project_id,
        "forecasts_total": len(forecasts),
        "forecasts_generated": generated,
        "forecasts_reviewed": reviewed,
    }
