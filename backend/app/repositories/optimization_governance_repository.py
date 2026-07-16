"""Репозиторий AI Optimization Governance (v0.8.2): governance + assignments + impacts + reviews.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Governance-слой: только управляет статусами/владельцами/impact; бизнес/KPI не меняет.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models.governance_review import GovernanceReview
from app.models.optimization_governance import OptimizationGovernance
from app.models.optimization_impact import OptimizationImpact
from app.models.optimization_owner_assignment import OptimizationOwnerAssignment

# Поля governance, которые можно обновлять (whitelist).
_GOVERNANCE_FIELDS: frozenset[str] = frozenset(
    {"status", "approval_status", "priority", "owner_user_id", "review_notes"}
)
_IMPACT_FIELDS: frozenset[str] = frozenset(
    {"status", "expected_impact", "actual_impact", "impact_score"}
)


# ---------------------------------------------------------------------------- #
# Governance                                                                   #
# ---------------------------------------------------------------------------- #


def create_governance(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    optimization_id: int,
    priority: str = "medium",
    status: str = "identified",
    approval_status: str = "pending",
    owner_user_id: int | None = None,
    review_notes: str | None = None,
) -> OptimizationGovernance:
    """Создать governance-запись для оптимизации."""
    governance = OptimizationGovernance(
        project_id=project_id,
        account_id=account_id,
        optimization_id=optimization_id,
        priority=priority,
        status=status,
        approval_status=approval_status,
        owner_user_id=owner_user_id,
        review_notes=review_notes,
    )
    db.add(governance)
    db.commit()
    db.refresh(governance)
    return governance


def get_governance(db: Session, governance_id: int) -> OptimizationGovernance | None:
    """Governance по id (или None)."""
    return db.get(OptimizationGovernance, governance_id)


def list_governances(
    db: Session,
    project_id: int,
    *,
    status: str | None = None,
    approval_status: str | None = None,
    limit: int = 200,
) -> list[OptimizationGovernance]:
    """Governance-записи проекта (свежие сверху), опционально по статусам."""
    stmt = select(OptimizationGovernance).where(OptimizationGovernance.project_id == project_id)
    if status is not None:
        stmt = stmt.where(OptimizationGovernance.status == status)
    if approval_status is not None:
        stmt = stmt.where(OptimizationGovernance.approval_status == approval_status)
    stmt = stmt.order_by(OptimizationGovernance.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def list_governances_by_optimization(
    db: Session, project_id: int, optimization_id: int
) -> list[OptimizationGovernance]:
    """Governance по конкретной оптимизации (для идемпотентности)."""
    stmt = select(OptimizationGovernance).where(
        OptimizationGovernance.project_id == project_id,
        OptimizationGovernance.optimization_id == optimization_id,
    )
    return list(db.execute(stmt).scalars().all())


def update_governance(
    db: Session, governance: OptimizationGovernance, **fields: Any
) -> OptimizationGovernance:
    """Обновить поля governance (только whitelist)."""
    for key, value in fields.items():
        if key in _GOVERNANCE_FIELDS:
            setattr(governance, key, value)
    db.commit()
    db.refresh(governance)
    return governance


def approve(db: Session, governance: OptimizationGovernance) -> OptimizationGovernance:
    """Согласовать: approval_status=approved, status=approved. НЕ запускает."""
    return update_governance(db, governance, approval_status="approved", status="approved")


def reject(db: Session, governance: OptimizationGovernance) -> OptimizationGovernance:
    """Отклонить: approval_status=rejected, status=rejected."""
    return update_governance(db, governance, approval_status="rejected", status="rejected")


# ---------------------------------------------------------------------------- #
# Owner assignments                                                            #
# ---------------------------------------------------------------------------- #


def assign_owner(
    db: Session, governance: OptimizationGovernance, owner_user_id: int, *, role: str = "owner"
) -> OptimizationOwnerAssignment:
    """Назначить владельца: закрыть активные назначения, создать новое, обновить governance."""
    db.execute(
        update(OptimizationOwnerAssignment)
        .where(
            OptimizationOwnerAssignment.governance_id == governance.id,
            OptimizationOwnerAssignment.released_at.is_(None),
        )
        .values(released_at=func.now())
    )
    assignment = OptimizationOwnerAssignment(
        governance_id=governance.id, owner_user_id=owner_user_id, role=role
    )
    db.add(assignment)
    governance.owner_user_id = owner_user_id
    db.commit()
    db.refresh(assignment)
    db.refresh(governance)
    return assignment


def list_owner_assignments(
    db: Session, governance_id: int, *, limit: int = 200
) -> list[OptimizationOwnerAssignment]:
    """История назначений governance (свежие сверху)."""
    stmt = (
        select(OptimizationOwnerAssignment)
        .where(OptimizationOwnerAssignment.governance_id == governance_id)
        .order_by(OptimizationOwnerAssignment.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Reviews                                                                      #
# ---------------------------------------------------------------------------- #


def create_review(
    db: Session,
    *,
    governance_id: int,
    reviewer_user_id: int | None,
    decision: str = "comment",
    comment: str | None = None,
) -> GovernanceReview:
    """Создать решение ревью (append-only)."""
    review = GovernanceReview(
        governance_id=governance_id,
        reviewer_user_id=reviewer_user_id,
        decision=decision,
        comment=comment,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


def list_reviews(db: Session, governance_id: int, *, limit: int = 200) -> list[GovernanceReview]:
    """История ревью governance (свежие сверху)."""
    stmt = (
        select(GovernanceReview)
        .where(GovernanceReview.governance_id == governance_id)
        .order_by(GovernanceReview.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def list_reviews_for_project(
    db: Session, project_id: int, *, limit: int = 200
) -> list[GovernanceReview]:
    """Все ревью проекта (join через governance), свежие сверху."""
    stmt = (
        select(GovernanceReview)
        .join(
            OptimizationGovernance,
            GovernanceReview.governance_id == OptimizationGovernance.id,
        )
        .where(OptimizationGovernance.project_id == project_id)
        .order_by(GovernanceReview.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Impacts                                                                      #
# ---------------------------------------------------------------------------- #


def create_impact(
    db: Session,
    *,
    governance_id: int,
    experiment_id: int | None = None,
    status: str = "unknown",
    expected_impact: dict[str, Any] | None = None,
    actual_impact: dict[str, Any] | None = None,
    impact_score: float = 0.0,
) -> OptimizationImpact:
    """Создать запись impact."""
    impact = OptimizationImpact(
        governance_id=governance_id,
        experiment_id=experiment_id,
        status=status,
        expected_impact=expected_impact or {},
        actual_impact=actual_impact or {},
        impact_score=float(impact_score or 0.0),
    )
    db.add(impact)
    db.commit()
    db.refresh(impact)
    return impact


def get_latest_impact(db: Session, governance_id: int) -> OptimizationImpact | None:
    """Последний impact governance (или None)."""
    stmt = (
        select(OptimizationImpact)
        .where(OptimizationImpact.governance_id == governance_id)
        .order_by(OptimizationImpact.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def list_impacts(db: Session, governance_id: int, *, limit: int = 200) -> list[OptimizationImpact]:
    """История impact governance (свежие сверху)."""
    stmt = (
        select(OptimizationImpact)
        .where(OptimizationImpact.governance_id == governance_id)
        .order_by(OptimizationImpact.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_impact(db: Session, impact: OptimizationImpact, **fields: Any) -> OptimizationImpact:
    """Обновить поля impact (только whitelist)."""
    for key, value in fields.items():
        if key in _IMPACT_FIELDS:
            setattr(impact, key, value)
    db.commit()
    db.refresh(impact)
    return impact


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_governance_view(governance: OptimizationGovernance) -> dict[str, Any]:
    """Безопасное представление governance (без секретов)."""
    return {
        "id": governance.id,
        "project_id": governance.project_id,
        "optimization_id": governance.optimization_id,
        "status": governance.status,
        "approval_status": governance.approval_status,
        "priority": governance.priority,
        "owner_user_id": governance.owner_user_id,
        "review_notes": governance.review_notes,
        "created_at": governance.created_at.isoformat() if governance.created_at else None,
        "updated_at": governance.updated_at.isoformat() if governance.updated_at else None,
    }


def public_review_view(review: GovernanceReview) -> dict[str, Any]:
    """Безопасное представление ревью."""
    return {
        "id": review.id,
        "governance_id": review.governance_id,
        "reviewer_user_id": review.reviewer_user_id,
        "decision": review.decision,
        "comment": review.comment,
        "created_at": review.created_at.isoformat() if review.created_at else None,
    }


def public_impact_view(impact: OptimizationImpact) -> dict[str, Any]:
    """Безопасное представление impact."""
    return {
        "id": impact.id,
        "governance_id": impact.governance_id,
        "experiment_id": impact.experiment_id,
        "status": impact.status,
        "expected_impact": dict(impact.expected_impact or {}),
        "actual_impact": dict(impact.actual_impact or {}),
        "impact_score": round(float(impact.impact_score or 0.0), 1),
        "created_at": impact.created_at.isoformat() if impact.created_at else None,
        "updated_at": impact.updated_at.isoformat() if impact.updated_at else None,
    }


def public_assignment_view(assignment: OptimizationOwnerAssignment) -> dict[str, Any]:
    """Безопасное представление назначения владельца."""
    return {
        "id": assignment.id,
        "governance_id": assignment.governance_id,
        "owner_user_id": assignment.owner_user_id,
        "role": assignment.role,
        "assigned_at": assignment.assigned_at.isoformat() if assignment.assigned_at else None,
        "released_at": assignment.released_at.isoformat() if assignment.released_at else None,
    }


# ---------------------------------------------------------------------------- #
# Portfolio metrics (DB-агрегаты)                                              #
# ---------------------------------------------------------------------------- #


def get_portfolio_metrics(db: Session, project_id: int) -> dict[str, Any]:
    """Метрики портфеля: счётчики governance по статусам + средний impact (DB-агрегаты)."""
    gov_where = OptimizationGovernance.project_id == project_id

    def _count(*conditions: Any) -> int:
        stmt = (
            select(func.count()).select_from(OptimizationGovernance).where(gov_where, *conditions)
        )
        return int(db.execute(stmt).scalar_one() or 0)

    total = _count()
    approved = _count(OptimizationGovernance.approval_status == "approved")
    pending = _count(OptimizationGovernance.approval_status == "pending")
    active = _count(OptimizationGovernance.status == "active")
    completed = _count(OptimizationGovernance.status == "completed")

    impact_join = (
        select(func.avg(OptimizationImpact.impact_score))
        .select_from(OptimizationImpact)
        .join(
            OptimizationGovernance,
            OptimizationImpact.governance_id == OptimizationGovernance.id,
        )
        .where(OptimizationGovernance.project_id == project_id)
    )
    avg_impact = db.execute(impact_join).scalar_one()
    positive_impacts = int(
        db.execute(
            select(func.count())
            .select_from(OptimizationImpact)
            .join(
                OptimizationGovernance,
                OptimizationImpact.governance_id == OptimizationGovernance.id,
            )
            .where(
                OptimizationGovernance.project_id == project_id,
                OptimizationImpact.status == "positive",
            )
        ).scalar_one()
        or 0
    )
    return {
        "project_id": project_id,
        "total": total,
        "approved": approved,
        "pending": pending,
        "active": active,
        "completed": completed,
        "avg_impact_score": round(float(avg_impact or 0.0), 1),
        "positive_impacts": positive_impacts,
    }
