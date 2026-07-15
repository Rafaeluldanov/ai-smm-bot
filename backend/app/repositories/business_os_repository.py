"""Репозиторий Autonomous Business OS (v0.7.0): цели + планы + действия.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_executive_plan import AIExecutivePlan
from app.models.business_action import BusinessAction
from app.models.business_objective import BusinessObjective

# Поля цели, которые можно обновлять.
_OBJECTIVE_FIELDS: frozenset[str] = frozenset(
    {"title", "description", "target_value", "current_value", "unit", "deadline", "status"}
)

# Открытые (ещё не терминальные) статусы бизнес-действия — единый источник для reassign и сводки.
_OPEN_ACTION_STATUSES: tuple[str, ...] = ("generated", "accepted")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Objectives                                                                   #
# ---------------------------------------------------------------------------- #


def create_objective(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    type: str,
    title: str,
    description: str | None = None,
    target_value: float = 0.0,
    current_value: float = 0.0,
    unit: str | None = None,
    deadline: datetime | None = None,
    objective_metadata: dict[str, Any] | None = None,
) -> BusinessObjective:
    """Создать бизнес-цель (status=draft)."""
    objective = BusinessObjective(
        project_id=project_id,
        account_id=account_id,
        type=type,
        title=title[:255],
        description=description,
        target_value=float(target_value or 0.0),
        current_value=float(current_value or 0.0),
        unit=unit,
        deadline=deadline,
        status="draft",
        objective_metadata=objective_metadata or {},
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


def get_objective(db: Session, objective_id: int) -> BusinessObjective | None:
    """Цель по id (или None)."""
    return db.get(BusinessObjective, objective_id)


def list_objectives(db: Session, project_id: int, *, limit: int = 200) -> list[BusinessObjective]:
    """Цели проекта (свежие сверху)."""
    stmt = (
        select(BusinessObjective)
        .where(BusinessObjective.project_id == project_id)
        .order_by(BusinessObjective.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_objective(db: Session, objective: BusinessObjective, **fields: Any) -> BusinessObjective:
    """Обновить поля цели (только белый список)."""
    for key, value in fields.items():
        if key in _OBJECTIVE_FIELDS:
            setattr(objective, key, value)
    db.commit()
    db.refresh(objective)
    return objective


# ---------------------------------------------------------------------------- #
# Executive plans                                                              #
# ---------------------------------------------------------------------------- #


def create_plan(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    objective_id: int | None = None,
    executive_summary: str | None = None,
    current_state: dict[str, Any] | None = None,
    priority_actions: list[Any] | None = None,
    risks: list[Any] | None = None,
    opportunities: list[Any] | None = None,
    expected_outcomes: dict[str, Any] | None = None,
    confidence_score: float = 0.0,
) -> AIExecutivePlan:
    """Создать исполнительный план (status=active)."""
    plan = AIExecutivePlan(
        project_id=project_id,
        account_id=account_id,
        objective_id=objective_id,
        status="active",
        executive_summary=executive_summary,
        current_state=current_state or {},
        priority_actions=priority_actions or [],
        risks=risks or [],
        opportunities=opportunities or [],
        expected_outcomes=expected_outcomes or {},
        confidence_score=float(confidence_score or 0.0),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_plan(db: Session, plan_id: int) -> AIExecutivePlan | None:
    """План по id (или None)."""
    return db.get(AIExecutivePlan, plan_id)


def get_latest_plan(db: Session, project_id: int) -> AIExecutivePlan | None:
    """Последний исполнительный план проекта (или None)."""
    stmt = (
        select(AIExecutivePlan)
        .where(AIExecutivePlan.project_id == project_id)
        .order_by(AIExecutivePlan.id.desc())
    )
    return db.execute(stmt).scalars().first()


# ---------------------------------------------------------------------------- #
# Business actions                                                             #
# ---------------------------------------------------------------------------- #


def create_action(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    plan_id: int | None,
    action_type: str,
    title: str,
    priority: float = 0.0,
    description: str | None = None,
    reasoning: list[Any] | None = None,
    expected_impact: dict[str, Any] | None = None,
    source_modules: list[Any] | None = None,
    apply_payload: dict[str, Any] | None = None,
) -> BusinessAction:
    """Создать бизнес-действие (status=generated)."""
    action = BusinessAction(
        project_id=project_id,
        account_id=account_id,
        plan_id=plan_id,
        action_type=action_type,
        priority=float(priority or 0.0),
        status="generated",
        title=title[:255],
        description=description,
        reasoning=reasoning or [],
        expected_impact=expected_impact or {},
        source_modules=source_modules or [],
        apply_payload=apply_payload or {},
    )
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def get_action(db: Session, action_id: int) -> BusinessAction | None:
    """Действие по id (или None)."""
    return db.get(BusinessAction, action_id)


def list_actions(
    db: Session,
    project_id: int,
    *,
    status: str | None = None,
    plan_id: int | None = None,
    limit: int = 200,
) -> list[BusinessAction]:
    """Действия проекта (по приоритету), с фильтрами."""
    stmt = select(BusinessAction).where(BusinessAction.project_id == project_id)
    if status is not None:
        stmt = stmt.where(BusinessAction.status == status)
    if plan_id is not None:
        stmt = stmt.where(BusinessAction.plan_id == plan_id)
    stmt = stmt.order_by(BusinessAction.priority.desc(), BusinessAction.id.desc()).limit(
        max(1, min(limit, 1000))
    )
    return list(db.execute(stmt).scalars().all())


def set_action_status(
    db: Session,
    action: BusinessAction,
    status: str,
    *,
    stamp_reviewed: bool = False,
    stamp_applied: bool = False,
) -> BusinessAction:
    """Сменить статус действия с метками времени."""
    action.status = status
    if stamp_reviewed:
        action.reviewed_at = _now()
    if stamp_applied:
        action.applied_at = _now()
    db.commit()
    db.refresh(action)
    return action


def accept_action(db: Session, action: BusinessAction) -> BusinessAction:
    """Одобрить действие (status=accepted)."""
    return set_action_status(db, action, "accepted", stamp_reviewed=True)


def reject_action(db: Session, action: BusinessAction) -> BusinessAction:
    """Отклонить действие (status=rejected)."""
    return set_action_status(db, action, "rejected", stamp_reviewed=True)


def apply_action(db: Session, action: BusinessAction) -> BusinessAction:
    """Пометить действие применённым (status=applied)."""
    return set_action_status(db, action, "applied", stamp_applied=True)


def list_open_actions(db: Session, project_id: int) -> list[BusinessAction]:
    """Открытые (generated/accepted) действия проекта по убыванию приоритета."""
    stmt = (
        select(BusinessAction)
        .where(BusinessAction.project_id == project_id)
        .where(BusinessAction.status.in_(_OPEN_ACTION_STATUSES))
        .order_by(BusinessAction.priority.desc(), BusinessAction.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def reassign_open_actions_to_plan(
    db: Session, project_id: int, plan_id: int
) -> list[BusinessAction]:
    """Привязать все ещё открытые (generated/accepted) действия проекта к новому плану.

    Терминальные действия (applied/rejected) остаются за своими историческими планами.
    Возвращает открытые действия проекта по убыванию приоритета — актуальный набор плана.
    """
    actions = list_open_actions(db, project_id)
    for action in actions:
        action.plan_id = plan_id
    db.commit()
    return actions


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_objective_view(objective: BusinessObjective) -> dict[str, Any]:
    """Безопасное представление цели (без секретов)."""
    return {
        "id": objective.id,
        "project_id": objective.project_id,
        "type": objective.type,
        "title": objective.title,
        "description": objective.description,
        "target_value": round(float(objective.target_value or 0.0), 2),
        "current_value": round(float(objective.current_value or 0.0), 2),
        "unit": objective.unit,
        "deadline": objective.deadline.isoformat() if objective.deadline else None,
        "status": objective.status,
        "created_at": objective.created_at.isoformat() if objective.created_at else None,
    }


def public_plan_view(plan: AIExecutivePlan) -> dict[str, Any]:
    """Безопасное представление плана (без секретов)."""
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "objective_id": plan.objective_id,
        "status": plan.status,
        "executive_summary": plan.executive_summary,
        "current_state": dict(plan.current_state or {}),
        "priority_actions": list(plan.priority_actions or []),
        "risks": list(plan.risks or []),
        "opportunities": list(plan.opportunities or []),
        "expected_outcomes": dict(plan.expected_outcomes or {}),
        "confidence_score": round(float(plan.confidence_score or 0.0), 1),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
    }


def public_action_view(action: BusinessAction) -> dict[str, Any]:
    """Безопасное представление действия."""
    return {
        "id": action.id,
        "project_id": action.project_id,
        "plan_id": action.plan_id,
        "action_type": action.action_type,
        "priority": round(float(action.priority or 0.0), 1),
        "status": action.status,
        "title": action.title,
        "description": action.description,
        "reasoning": list(action.reasoning or []),
        "expected_impact": dict(action.expected_impact or {}),
        "source_modules": list(action.source_modules or []),
        "reviewed_at": action.reviewed_at.isoformat() if action.reviewed_at else None,
        "applied_at": action.applied_at.isoformat() if action.applied_at else None,
        "created_at": action.created_at.isoformat() if action.created_at else None,
    }


def build_business_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка бизнеса: последний план + счётчики целей/действий."""
    plan = get_latest_plan(db, project_id)
    # «Открытые» действия = generated + accepted (тот же набор, что reassign/get_plan),
    # иначе счётчик сводки расходился бы с планом после accept.
    open_actions = list_open_actions(db, project_id)
    return {
        "project_id": project_id,
        "has_plan": plan is not None,
        "latest_plan": public_plan_view(plan) if plan is not None else None,
        "objectives_count": len(list_objectives(db, project_id)),
        "actions_open": len(open_actions),
    }
