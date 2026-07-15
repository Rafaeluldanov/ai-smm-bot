"""Репозиторий AI Operations Control Center (v0.7.3): снапшоты + риски + рекомендации.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.operations_recommendation import OperationsRecommendation
from app.models.operations_risk import OperationsRisk
from app.models.operations_snapshot import OperationsSnapshot


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Snapshots                                                                    #
# ---------------------------------------------------------------------------- #


def create_snapshot(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    health_score: float,
    status: str,
    metrics: dict[str, Any] | None = None,
    business_state: dict[str, Any] | None = None,
    growth_state: dict[str, Any] | None = None,
    sales_state: dict[str, Any] | None = None,
    workflow_state: dict[str, Any] | None = None,
    risk_count: int = 0,
) -> OperationsSnapshot:
    """Создать операционный снапшот (отметка времени generated_at)."""
    snapshot = OperationsSnapshot(
        project_id=project_id,
        account_id=account_id,
        health_score=round(float(health_score or 0.0), 1),
        status=status,
        metrics=metrics or {},
        business_state=business_state or {},
        growth_state=growth_state or {},
        sales_state=sales_state or {},
        workflow_state=workflow_state or {},
        risk_count=int(risk_count or 0),
        generated_at=_now(),
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_snapshot(db: Session, snapshot_id: int) -> OperationsSnapshot | None:
    """Снапшот по id (или None)."""
    return db.get(OperationsSnapshot, snapshot_id)


def get_latest_snapshot(db: Session, project_id: int) -> OperationsSnapshot | None:
    """Последний операционный снапшот проекта (или None)."""
    stmt = (
        select(OperationsSnapshot)
        .where(OperationsSnapshot.project_id == project_id)
        .order_by(OperationsSnapshot.id.desc())
    )
    return db.execute(stmt).scalars().first()


def list_snapshots(db: Session, project_id: int, *, limit: int = 30) -> list[OperationsSnapshot]:
    """История снапшотов проекта (свежие сверху)."""
    stmt = (
        select(OperationsSnapshot)
        .where(OperationsSnapshot.project_id == project_id)
        .order_by(OperationsSnapshot.id.desc())
        .limit(max(1, min(limit, 365)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Risks                                                                        #
# ---------------------------------------------------------------------------- #


def create_risk(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    risk_type: str,
    title: str,
    severity: str = "medium",
    description: str | None = None,
    source_module: str | None = None,
    source_entity_id: int | None = None,
    impact: dict[str, Any] | None = None,
    recommended_action: dict[str, Any] | None = None,
) -> OperationsRisk:
    """Создать операционный риск (status=open)."""
    risk = OperationsRisk(
        project_id=project_id,
        account_id=account_id,
        risk_type=risk_type,
        title=title[:255],
        severity=severity,
        status="open",
        description=description,
        source_module=source_module,
        source_entity_id=source_entity_id,
        impact=impact or {},
        recommended_action=recommended_action or {},
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


def get_risk(db: Session, risk_id: int) -> OperationsRisk | None:
    """Риск по id (или None)."""
    return db.get(OperationsRisk, risk_id)


def list_risks(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[OperationsRisk]:
    """Риски проекта (свежие сверху), опционально по статусу."""
    stmt = select(OperationsRisk).where(OperationsRisk.project_id == project_id)
    if status is not None:
        stmt = stmt.where(OperationsRisk.status == status)
    stmt = stmt.order_by(OperationsRisk.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def list_active_risks(db: Session, project_id: int, *, limit: int = 200) -> list[OperationsRisk]:
    """Открытые риски проекта."""
    return list_risks(db, project_id, status="open", limit=limit)


def find_open_risk_by_type(db: Session, project_id: int, risk_type: str) -> OperationsRisk | None:
    """Открытый риск заданного типа (для дедупа при повторном анализе)."""
    stmt = (
        select(OperationsRisk)
        .where(OperationsRisk.project_id == project_id)
        .where(OperationsRisk.risk_type == risk_type)
        .where(OperationsRisk.status == "open")
        .order_by(OperationsRisk.id.desc())
    )
    return db.execute(stmt).scalars().first()


def resolve_risk(db: Session, risk: OperationsRisk) -> OperationsRisk:
    """Пометить риск решённым (status=resolved, resolved_at). НЕ выполняет действий."""
    risk.status = "resolved"
    risk.resolved_at = _now()
    db.commit()
    db.refresh(risk)
    return risk


# ---------------------------------------------------------------------------- #
# Recommendations                                                              #
# ---------------------------------------------------------------------------- #


def create_recommendation(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    priority: str,
    title: str,
    description: str | None = None,
    reasoning: list[Any] | None = None,
    source_signals: list[Any] | None = None,
    expected_impact: dict[str, Any] | None = None,
) -> OperationsRecommendation:
    """Создать операционную рекомендацию (status=generated)."""
    recommendation = OperationsRecommendation(
        project_id=project_id,
        account_id=account_id,
        priority=priority,
        title=title[:255],
        description=description,
        reasoning=reasoning or [],
        source_signals=source_signals or [],
        expected_impact=expected_impact or {},
        status="generated",
    )
    db.add(recommendation)
    db.commit()
    db.refresh(recommendation)
    return recommendation


def get_recommendation(db: Session, recommendation_id: int) -> OperationsRecommendation | None:
    """Рекомендация по id (или None)."""
    return db.get(OperationsRecommendation, recommendation_id)


def list_recommendations(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[OperationsRecommendation]:
    """Рекомендации проекта (свежие сверху), опционально по статусу."""
    stmt = select(OperationsRecommendation).where(OperationsRecommendation.project_id == project_id)
    if status is not None:
        stmt = stmt.where(OperationsRecommendation.status == status)
    stmt = stmt.order_by(OperationsRecommendation.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def find_recommendation_by_title(
    db: Session, project_id: int, title: str
) -> OperationsRecommendation | None:
    """Рекомендация проекта с тем же заголовком в любом статусе (для дедупа)."""
    stmt = (
        select(OperationsRecommendation)
        .where(OperationsRecommendation.project_id == project_id)
        .where(OperationsRecommendation.title == title[:255])
        .order_by(OperationsRecommendation.id.desc())
    )
    return db.execute(stmt).scalars().first()


def set_recommendation_status(
    db: Session, recommendation: OperationsRecommendation, status: str
) -> OperationsRecommendation:
    """Сменить статус рекомендации (accepted/rejected). НЕ выполняет действий."""
    recommendation.status = status
    db.commit()
    db.refresh(recommendation)
    return recommendation


def accept_recommendation(
    db: Session, recommendation: OperationsRecommendation
) -> OperationsRecommendation:
    """Одобрить рекомендацию (status=accepted)."""
    return set_recommendation_status(db, recommendation, "accepted")


def reject_recommendation(
    db: Session, recommendation: OperationsRecommendation
) -> OperationsRecommendation:
    """Отклонить рекомендацию (status=rejected)."""
    return set_recommendation_status(db, recommendation, "rejected")


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_snapshot_view(snapshot: OperationsSnapshot) -> dict[str, Any]:
    """Безопасное представление снапшота (без секретов)."""
    return {
        "id": snapshot.id,
        "project_id": snapshot.project_id,
        "health_score": round(float(snapshot.health_score or 0.0), 1),
        "status": snapshot.status,
        "metrics": dict(snapshot.metrics or {}),
        "business_state": dict(snapshot.business_state or {}),
        "growth_state": dict(snapshot.growth_state or {}),
        "sales_state": dict(snapshot.sales_state or {}),
        "workflow_state": dict(snapshot.workflow_state or {}),
        "risk_count": snapshot.risk_count,
        "generated_at": snapshot.generated_at.isoformat() if snapshot.generated_at else None,
        "created_at": snapshot.created_at.isoformat() if snapshot.created_at else None,
    }


def public_risk_view(risk: OperationsRisk) -> dict[str, Any]:
    """Безопасное представление риска."""
    return {
        "id": risk.id,
        "project_id": risk.project_id,
        "risk_type": risk.risk_type,
        "severity": risk.severity,
        "status": risk.status,
        "title": risk.title,
        "description": risk.description,
        "source_module": risk.source_module,
        "source_entity_id": risk.source_entity_id,
        "impact": dict(risk.impact or {}),
        "recommended_action": dict(risk.recommended_action or {}),
        "resolved_at": risk.resolved_at.isoformat() if risk.resolved_at else None,
        "created_at": risk.created_at.isoformat() if risk.created_at else None,
    }


def public_recommendation_view(recommendation: OperationsRecommendation) -> dict[str, Any]:
    """Безопасное представление рекомендации."""
    return {
        "id": recommendation.id,
        "project_id": recommendation.project_id,
        "priority": recommendation.priority,
        "title": recommendation.title,
        "description": recommendation.description,
        "reasoning": list(recommendation.reasoning or []),
        "source_signals": list(recommendation.source_signals or []),
        "expected_impact": dict(recommendation.expected_impact or {}),
        "status": recommendation.status,
        "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
    }


def build_operations_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка операционного центра: последний снапшот + счётчики рисков/рекомендаций."""
    snapshot = get_latest_snapshot(db, project_id)
    open_risks = list_active_risks(db, project_id)
    open_recs = list_recommendations(db, project_id, status="generated")
    return {
        "project_id": project_id,
        "has_snapshot": snapshot is not None,
        "latest_snapshot": public_snapshot_view(snapshot) if snapshot is not None else None,
        "risks_open": len(open_risks),
        "recommendations_open": len(open_recs),
    }
