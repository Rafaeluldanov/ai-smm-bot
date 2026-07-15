"""Репозиторий AI Business Planner (v0.7.7): цели + планы + квартальные цели + вехи.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
План — только рекомендация; approve/convert меняют лишь статус / создают ЧЕРНОВИК процесса.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.business_goal import BusinessGoal
from app.models.plan_milestone import PlanMilestone
from app.models.quarter_objective import QuarterObjective
from app.models.strategic_plan import StrategicPlan

# Поля, которые можно обновлять (whitelist) — статусы + результат генерации.
_GOAL_FIELDS: frozenset[str] = frozenset(
    {"status", "title", "description", "target_value", "current_value", "target_date"}
)
_PLAN_FIELDS: frozenset[str] = frozenset(
    {"status", "title", "summary", "gap_analysis", "strategy", "confidence_score"}
)
_OBJECTIVE_FIELDS: frozenset[str] = frozenset({"status", "title", "description", "kpi", "priority"})
_MILESTONE_FIELDS: frozenset[str] = frozenset({"status", "title", "description", "target_date"})


# ---------------------------------------------------------------------------- #
# Goals                                                                        #
# ---------------------------------------------------------------------------- #


def create_goal(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    goal_type: str,
    title: str,
    description: str | None = None,
    target_value: float = 0.0,
    current_value: float = 0.0,
    target_date: datetime | None = None,
    status: str = "active",
    goal_metadata: dict[str, Any] | None = None,
) -> BusinessGoal:
    """Создать бизнес-цель (status=active по умолчанию)."""
    goal = BusinessGoal(
        project_id=project_id,
        account_id=account_id,
        goal_type=goal_type,
        title=title[:255],
        description=description,
        target_value=float(target_value or 0.0),
        current_value=float(current_value or 0.0),
        target_date=target_date,
        status=status,
        goal_metadata=goal_metadata or {},
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def get_goal(db: Session, goal_id: int) -> BusinessGoal | None:
    """Цель по id (или None)."""
    return db.get(BusinessGoal, goal_id)


def list_goals(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[BusinessGoal]:
    """Цели проекта (свежие сверху), опционально по статусу."""
    stmt = select(BusinessGoal).where(BusinessGoal.project_id == project_id)
    if status is not None:
        stmt = stmt.where(BusinessGoal.status == status)
    stmt = stmt.order_by(BusinessGoal.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_goal(db: Session, goal: BusinessGoal, **fields: Any) -> BusinessGoal:
    """Обновить поля цели (только whitelist)."""
    for key, value in fields.items():
        if key in _GOAL_FIELDS:
            setattr(goal, key, value)
    db.commit()
    db.refresh(goal)
    return goal


# ---------------------------------------------------------------------------- #
# Plans                                                                        #
# ---------------------------------------------------------------------------- #


def create_plan(
    db: Session,
    *,
    goal_id: int,
    title: str,
    status: str = "generated",
    summary: str | None = None,
    gap_analysis: dict[str, Any] | None = None,
    strategy: dict[str, Any] | None = None,
    confidence_score: float = 0.0,
) -> StrategicPlan:
    """Создать стратегический план (status=generated по умолчанию)."""
    plan = StrategicPlan(
        goal_id=goal_id,
        title=title[:255],
        status=status,
        summary=summary,
        gap_analysis=gap_analysis or {},
        strategy=strategy or {},
        confidence_score=float(confidence_score or 0.0),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_plan(db: Session, plan_id: int) -> StrategicPlan | None:
    """План по id (или None)."""
    return db.get(StrategicPlan, plan_id)


def list_plans(db: Session, goal_id: int, *, limit: int = 100) -> list[StrategicPlan]:
    """Планы цели (свежие сверху)."""
    stmt = (
        select(StrategicPlan)
        .where(StrategicPlan.goal_id == goal_id)
        .order_by(StrategicPlan.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_plan(db: Session, plan: StrategicPlan, **fields: Any) -> StrategicPlan:
    """Обновить поля плана (только whitelist)."""
    for key, value in fields.items():
        if key in _PLAN_FIELDS:
            setattr(plan, key, value)
    db.commit()
    db.refresh(plan)
    return plan


# ---------------------------------------------------------------------------- #
# Objectives                                                                   #
# ---------------------------------------------------------------------------- #


def create_objective(
    db: Session,
    *,
    plan_id: int,
    quarter: str,
    title: str,
    description: str | None = None,
    kpi: list[Any] | None = None,
    priority: str = "medium",
    status: str = "planned",
) -> QuarterObjective:
    """Создать квартальную цель."""
    objective = QuarterObjective(
        plan_id=plan_id,
        quarter=quarter,
        title=title[:255],
        description=description,
        kpi=kpi or [],
        priority=priority,
        status=status,
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


def get_objective(db: Session, objective_id: int) -> QuarterObjective | None:
    """Квартальная цель по id (или None)."""
    return db.get(QuarterObjective, objective_id)


def delete_objectives(db: Session, plan_id: int) -> None:
    """Удалить квартальные цели плана и их вехи (пересоздание при повторной генерации).

    Вехи удаляются ЯВНО, а не полагаясь на ON DELETE CASCADE БД (без него — напр. SQLite без
    PRAGMA foreign_keys — вехи бы «утекали» и переклеивались к новым целям).
    """
    objective_ids = [o.id for o in list_objectives(db, plan_id)]
    if objective_ids:
        db.execute(delete(PlanMilestone).where(PlanMilestone.objective_id.in_(objective_ids)))
        db.execute(delete(QuarterObjective).where(QuarterObjective.id.in_(objective_ids)))
    db.commit()


def list_objectives(db: Session, plan_id: int, *, limit: int = 100) -> list[QuarterObjective]:
    """Квартальные цели плана (по порядку создания)."""
    stmt = (
        select(QuarterObjective)
        .where(QuarterObjective.plan_id == plan_id)
        .order_by(QuarterObjective.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_objective(db: Session, objective: QuarterObjective, **fields: Any) -> QuarterObjective:
    """Обновить поля квартальной цели (только whitelist)."""
    for key, value in fields.items():
        if key in _OBJECTIVE_FIELDS:
            setattr(objective, key, value)
    db.commit()
    db.refresh(objective)
    return objective


# ---------------------------------------------------------------------------- #
# Milestones                                                                   #
# ---------------------------------------------------------------------------- #


def create_milestone(
    db: Session,
    *,
    objective_id: int,
    title: str,
    description: str | None = None,
    target_date: datetime | None = None,
    status: str = "planned",
    milestone_metadata: dict[str, Any] | None = None,
) -> PlanMilestone:
    """Создать веху квартальной цели."""
    milestone = PlanMilestone(
        objective_id=objective_id,
        title=title[:255],
        description=description,
        target_date=target_date,
        status=status,
        milestone_metadata=milestone_metadata or {},
    )
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def list_milestones(db: Session, objective_id: int, *, limit: int = 200) -> list[PlanMilestone]:
    """Вехи квартальной цели (по порядку создания)."""
    stmt = (
        select(PlanMilestone)
        .where(PlanMilestone.objective_id == objective_id)
        .order_by(PlanMilestone.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_goal_view(goal: BusinessGoal) -> dict[str, Any]:
    """Безопасное представление цели (без секретов)."""
    gap = round(float(goal.target_value or 0.0) - float(goal.current_value or 0.0), 2)
    return {
        "id": goal.id,
        "project_id": goal.project_id,
        "goal_type": goal.goal_type,
        "title": goal.title,
        "description": goal.description,
        "target_value": round(float(goal.target_value or 0.0), 2),
        "current_value": round(float(goal.current_value or 0.0), 2),
        "gap": gap,
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
        "status": goal.status,
        "metadata": dict(goal.goal_metadata or {}),
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


def public_plan_view(plan: StrategicPlan) -> dict[str, Any]:
    """Безопасное представление плана."""
    return {
        "id": plan.id,
        "goal_id": plan.goal_id,
        "status": plan.status,
        "title": plan.title,
        "summary": plan.summary,
        "gap_analysis": dict(plan.gap_analysis or {}),
        "strategy": dict(plan.strategy or {}),
        "confidence_score": round(float(plan.confidence_score or 0.0), 1),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def public_objective_view(objective: QuarterObjective) -> dict[str, Any]:
    """Безопасное представление квартальной цели."""
    return {
        "id": objective.id,
        "plan_id": objective.plan_id,
        "quarter": objective.quarter,
        "title": objective.title,
        "description": objective.description,
        "kpi": list(objective.kpi or []),
        "priority": objective.priority,
        "status": objective.status,
        "created_at": objective.created_at.isoformat() if objective.created_at else None,
        "updated_at": objective.updated_at.isoformat() if objective.updated_at else None,
    }


def public_milestone_view(milestone: PlanMilestone) -> dict[str, Any]:
    """Безопасное представление вехи."""
    return {
        "id": milestone.id,
        "objective_id": milestone.objective_id,
        "title": milestone.title,
        "description": milestone.description,
        "target_date": milestone.target_date.isoformat() if milestone.target_date else None,
        "status": milestone.status,
        "metadata": dict(milestone.milestone_metadata or {}),
        "created_at": milestone.created_at.isoformat() if milestone.created_at else None,
        "updated_at": milestone.updated_at.isoformat() if milestone.updated_at else None,
    }


def build_planner_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Business Planner: счётчики целей по ключевым статусам."""
    goals = list_goals(db, project_id)
    active = sum(1 for g in goals if g.status == "active")
    achieved = sum(1 for g in goals if g.status == "achieved")
    return {
        "project_id": project_id,
        "goals_total": len(goals),
        "goals_active": active,
        "goals_achieved": achieved,
    }
