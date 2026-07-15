"""Репозиторий AI Performance Intelligence (v0.7.9): снимки + метрики + отклонения + рекомендации.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Аналитический слой: только измеряет и советует; планы/KPI/бизнес не меняет.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.performance_deviation import PerformanceDeviation
from app.models.performance_metric import PerformanceMetric
from app.models.performance_recommendation import PerformanceRecommendation
from app.models.performance_snapshot import PerformanceSnapshot

# ---------------------------------------------------------------------------- #
# Snapshots                                                                    #
# ---------------------------------------------------------------------------- #


def create_snapshot(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    execution_plan_id: int | None = None,
    status: str = "healthy",
    performance_score: float = 0.0,
    metrics: dict[str, Any] | None = None,
    target_state: dict[str, Any] | None = None,
    actual_state: dict[str, Any] | None = None,
) -> PerformanceSnapshot:
    """Создать снимок эффективности (status=healthy по умолчанию)."""
    snapshot = PerformanceSnapshot(
        project_id=project_id,
        account_id=account_id,
        execution_plan_id=execution_plan_id,
        status=status,
        performance_score=float(performance_score or 0.0),
        metrics=metrics or {},
        target_state=target_state or {},
        actual_state=actual_state or {},
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_snapshot(db: Session, snapshot_id: int) -> PerformanceSnapshot | None:
    """Снимок по id (или None)."""
    return db.get(PerformanceSnapshot, snapshot_id)


def get_latest_snapshot(db: Session, project_id: int) -> PerformanceSnapshot | None:
    """Последний снимок проекта (свежий сверху) или None."""
    stmt = (
        select(PerformanceSnapshot)
        .where(PerformanceSnapshot.project_id == project_id)
        .order_by(PerformanceSnapshot.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def list_snapshots(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[PerformanceSnapshot]:
    """Снимки проекта (свежие сверху), опционально по статусу."""
    stmt = select(PerformanceSnapshot).where(PerformanceSnapshot.project_id == project_id)
    if status is not None:
        stmt = stmt.where(PerformanceSnapshot.status == status)
    stmt = stmt.order_by(PerformanceSnapshot.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Metrics                                                                       #
# ---------------------------------------------------------------------------- #


def create_metric(
    db: Session,
    *,
    snapshot_id: int,
    metric: str,
    target_value: float = 0.0,
    actual_value: float = 0.0,
    difference: float = 0.0,
    difference_percent: float = 0.0,
    status: str = "healthy",
    reasoning: list[Any] | None = None,
) -> PerformanceMetric:
    """Создать метрику эффективности (append-only)."""
    row = PerformanceMetric(
        snapshot_id=snapshot_id,
        metric=metric,
        target_value=float(target_value or 0.0),
        actual_value=float(actual_value or 0.0),
        difference=float(difference or 0.0),
        difference_percent=float(difference_percent or 0.0),
        status=status,
        reasoning=reasoning or [],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_metrics(db: Session, snapshot_id: int, *, limit: int = 500) -> list[PerformanceMetric]:
    """Метрики снимка (по порядку создания)."""
    stmt = (
        select(PerformanceMetric)
        .where(PerformanceMetric.snapshot_id == snapshot_id)
        .order_by(PerformanceMetric.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Deviations                                                                   #
# ---------------------------------------------------------------------------- #


def create_deviation(
    db: Session,
    *,
    snapshot_id: int,
    metric: str,
    title: str,
    deviation_type: str = "negative",
    impact: str = "medium",
    description: str | None = None,
    root_causes: list[Any] | None = None,
) -> PerformanceDeviation:
    """Создать отклонение эффективности (append-only)."""
    deviation = PerformanceDeviation(
        snapshot_id=snapshot_id,
        metric=metric,
        title=title[:255],
        deviation_type=deviation_type,
        impact=impact,
        description=description,
        root_causes=root_causes or [],
    )
    db.add(deviation)
    db.commit()
    db.refresh(deviation)
    return deviation


def list_deviations(
    db: Session, snapshot_id: int, *, limit: int = 200
) -> list[PerformanceDeviation]:
    """Отклонения снимка (по порядку создания)."""
    stmt = (
        select(PerformanceDeviation)
        .where(PerformanceDeviation.snapshot_id == snapshot_id)
        .order_by(PerformanceDeviation.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Recommendations                                                              #
# ---------------------------------------------------------------------------- #


def create_recommendation(
    db: Session,
    *,
    snapshot_id: int,
    title: str,
    priority: str = "medium",
    description: str | None = None,
    expected_effect: dict[str, Any] | None = None,
    status: str = "generated",
) -> PerformanceRecommendation:
    """Создать рекомендацию по эффективности."""
    recommendation = PerformanceRecommendation(
        snapshot_id=snapshot_id,
        title=title[:255],
        priority=priority,
        description=description,
        expected_effect=expected_effect or {},
        status=status,
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return recommendation


def list_recommendations(
    db: Session, snapshot_id: int, *, limit: int = 200
) -> list[PerformanceRecommendation]:
    """Рекомендации снимка (по порядку создания)."""
    stmt = (
        select(PerformanceRecommendation)
        .where(PerformanceRecommendation.snapshot_id == snapshot_id)
        .order_by(PerformanceRecommendation.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_snapshot_view(snapshot: PerformanceSnapshot) -> dict[str, Any]:
    """Безопасное представление снимка (без секретов)."""
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "execution_plan_id": snapshot.execution_plan_id,
        "status": snapshot.status,
        "performance_score": round(float(snapshot.performance_score or 0.0), 1),
        "metrics": dict(snapshot.metrics or {}),
        "target_state": dict(snapshot.target_state or {}),
        "actual_state": dict(snapshot.actual_state or {}),
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
        "updated_at": snapshot.updated_at.isoformat() if snapshot.updated_at else None,
    }


def public_metric_view(metric: PerformanceMetric) -> dict[str, Any]:
    """Безопасное представление метрики."""
    return {
        "id": metric.id,
        "snapshot_id": metric.snapshot_id,
        "metric": metric.metric,
        "target_value": round(float(metric.target_value or 0.0), 2),
        "actual_value": round(float(metric.actual_value or 0.0), 2),
        "difference": round(float(metric.difference or 0.0), 2),
        "difference_percent": round(float(metric.difference_percent or 0.0), 1),
        "status": metric.status,
        "reasoning": list(metric.reasoning or []),
        "created_at": metric.created_at.isoformat() if metric.created_at else None,
    }


def public_deviation_view(deviation: PerformanceDeviation) -> dict[str, Any]:
    """Безопасное представление отклонения."""
    return {
        "id": deviation.id,
        "snapshot_id": deviation.snapshot_id,
        "deviation_type": deviation.deviation_type,
        "metric": deviation.metric,
        "impact": deviation.impact,
        "title": deviation.title,
        "description": deviation.description,
        "root_causes": list(deviation.root_causes or []),
        "created_at": deviation.created_at.isoformat() if deviation.created_at else None,
    }


def public_recommendation_view(recommendation: PerformanceRecommendation) -> dict[str, Any]:
    """Безопасное представление рекомендации."""
    return {
        "id": recommendation.id,
        "snapshot_id": recommendation.snapshot_id,
        "priority": recommendation.priority,
        "title": recommendation.title,
        "description": recommendation.description,
        "expected_effect": dict(recommendation.expected_effect or {}),
        "status": recommendation.status,
        "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
        "updated_at": recommendation.updated_at.isoformat() if recommendation.updated_at else None,
    }


def build_performance_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Performance Intelligence: счётчики снимков + последний score."""
    snapshots = list_snapshots(db, project_id)
    latest = snapshots[0] if snapshots else None
    return {
        "project_id": project_id,
        "snapshots_total": len(snapshots),
        "latest_score": round(float(latest.performance_score), 1) if latest else None,
        "latest_status": latest.status if latest else None,
    }
