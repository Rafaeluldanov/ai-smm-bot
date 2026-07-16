"""Репозиторий AI Business OS Pilot (v0.9.1 + v1.0.0): воркспейсы/профили/цели/KPI/feedback.

Публичные представления без секретов/токенов. Tenant isolation — list по account_id + проверка на
сервис/API-слое. PILOT/advisory-слой: только описание пилота; бизнес/CRM не затрагивает.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pilot_business_profile import PilotBusinessProfile
from app.models.pilot_feedback import PilotFeedback
from app.models.pilot_goal import PilotGoal
from app.models.pilot_kpi import PilotKPI
from app.models.pilot_workspace import PilotWorkspace

# Поля, которые можно обновлять (whitelist).
_WORKSPACE_FIELDS: frozenset[str] = frozenset({"company_name", "industry", "status"})
_GOAL_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "current_value",
        "target_value",
        "unit",
        "deadline",
        "priority",
        "status",
    }
)
_KPI_FIELDS: frozenset[str] = frozenset(
    {"name", "current_value", "target_value", "unit", "frequency", "status"}
)
_FEEDBACK_FIELDS: frozenset[str] = frozenset({"comment", "result"})
_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "products",
        "services",
        "team",
        "sales_channels",
        "business_description",
        "current_revenue",
        "target_revenue",
        "kpi",
    }
)


# ---------------------------------------------------------------------------- #
# Workspaces                                                                   #
# ---------------------------------------------------------------------------- #


def create_workspace(
    db: Session,
    *,
    account_id: int | None,
    company_name: str,
    industry: str = "",
    status: str = "draft",
    created_by: int | None = None,
) -> PilotWorkspace:
    """Создать pilot-воркспейс."""
    workspace = PilotWorkspace(
        account_id=account_id,
        company_name=company_name[:255],
        industry=industry[:100],
        status=status,
        created_by=created_by,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def get_workspace(db: Session, workspace_id: int) -> PilotWorkspace | None:
    """Воркспейс по id (или None)."""
    return db.get(PilotWorkspace, workspace_id)


def list_workspaces(
    db: Session, *, account_id: int | None = None, limit: int = 200
) -> list[PilotWorkspace]:
    """Pilot-воркспейсы (свежие сверху), опционально по аккаунту (tenant isolation)."""
    stmt = select(PilotWorkspace)
    if account_id is not None:
        stmt = stmt.where(PilotWorkspace.account_id == account_id)
    stmt = stmt.order_by(PilotWorkspace.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_workspace(db: Session, workspace: PilotWorkspace, **fields: Any) -> PilotWorkspace:
    """Обновить поля воркспейса (только whitelist)."""
    for key, value in fields.items():
        if key in _WORKSPACE_FIELDS:
            setattr(workspace, key, value)
    db.commit()
    db.refresh(workspace)
    return workspace


# ---------------------------------------------------------------------------- #
# Business profiles                                                            #
# ---------------------------------------------------------------------------- #


def create_profile(
    db: Session,
    *,
    workspace_id: int,
    products: list[Any] | None = None,
    services: list[Any] | None = None,
    team: dict[str, Any] | None = None,
    sales_channels: list[Any] | None = None,
    business_description: str | None = None,
    current_revenue: float = 0.0,
    target_revenue: float = 0.0,
    kpi: dict[str, Any] | None = None,
) -> PilotBusinessProfile:
    """Создать бизнес-профиль пилота."""
    profile = PilotBusinessProfile(
        workspace_id=workspace_id,
        products=products or [],
        services=services or [],
        team=team or {},
        sales_channels=sales_channels or [],
        business_description=business_description,
        current_revenue=float(current_revenue or 0.0),
        target_revenue=float(target_revenue or 0.0),
        kpi=kpi or {},
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_profile(db: Session, workspace_id: int) -> PilotBusinessProfile | None:
    """Последний бизнес-профиль воркспейса (или None)."""
    stmt = (
        select(PilotBusinessProfile)
        .where(PilotBusinessProfile.workspace_id == workspace_id)
        .order_by(PilotBusinessProfile.id.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def update_profile(
    db: Session, profile: PilotBusinessProfile, **fields: Any
) -> PilotBusinessProfile:
    """Обновить поля профиля (только whitelist)."""
    for key, value in fields.items():
        if key in _PROFILE_FIELDS:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_workspace_view(workspace: PilotWorkspace) -> dict[str, Any]:
    """Безопасное представление воркспейса (без секретов)."""
    return {
        "id": workspace.id,
        "account_id": workspace.account_id,
        "company_name": workspace.company_name,
        "industry": workspace.industry,
        "status": workspace.status,
        "created_by": workspace.created_by,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def public_profile_view(profile: PilotBusinessProfile) -> dict[str, Any]:
    """Безопасное представление профиля (без секретов)."""
    return {
        "id": profile.id,
        "workspace_id": profile.workspace_id,
        "products": list(profile.products or []),
        "services": list(profile.services or []),
        "team": dict(profile.team or {}),
        "sales_channels": list(profile.sales_channels or []),
        "business_description": profile.business_description,
        "current_revenue": round(float(profile.current_revenue or 0.0), 2),
        "target_revenue": round(float(profile.target_revenue or 0.0), 2),
        "kpi": dict(profile.kpi or {}),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


# ---------------------------------------------------------------------------- #
# Goals (v1.0.0)                                                               #
# ---------------------------------------------------------------------------- #


def create_goal(
    db: Session,
    *,
    workspace_id: int,
    title: str,
    description: str | None = None,
    current_value: float = 0.0,
    target_value: float = 0.0,
    unit: str = "",
    deadline: datetime | None = None,
    priority: str = "medium",
    status: str = "active",
) -> PilotGoal:
    """Создать бизнес-цель пилота."""
    goal = PilotGoal(
        workspace_id=workspace_id,
        title=title[:255],
        description=description,
        current_value=float(current_value or 0.0),
        target_value=float(target_value or 0.0),
        unit=unit[:50],
        deadline=deadline,
        priority=priority,
        status=status,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


def get_goal(db: Session, goal_id: int) -> PilotGoal | None:
    """Цель по id (или None)."""
    return db.get(PilotGoal, goal_id)


def list_goals(
    db: Session, workspace_id: int, *, status: str | None = None, limit: int = 200
) -> list[PilotGoal]:
    """Цели воркспейса (свежие сверху), опционально по статусу."""
    stmt = select(PilotGoal).where(PilotGoal.workspace_id == workspace_id)
    if status is not None:
        stmt = stmt.where(PilotGoal.status == status)
    stmt = stmt.order_by(PilotGoal.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_goal(db: Session, goal: PilotGoal, **fields: Any) -> PilotGoal:
    """Обновить поля цели (только whitelist)."""
    for key, value in fields.items():
        if key in _GOAL_FIELDS:
            setattr(goal, key, value)
    db.commit()
    db.refresh(goal)
    return goal


# ---------------------------------------------------------------------------- #
# KPIs (v1.0.0)                                                                #
# ---------------------------------------------------------------------------- #


def create_kpi(
    db: Session,
    *,
    workspace_id: int,
    name: str,
    current_value: float = 0.0,
    target_value: float = 0.0,
    unit: str = "",
    frequency: str = "monthly",
    status: str = "active",
) -> PilotKPI:
    """Создать KPI пилота."""
    kpi = PilotKPI(
        workspace_id=workspace_id,
        name=name[:255],
        current_value=float(current_value or 0.0),
        target_value=float(target_value or 0.0),
        unit=unit[:50],
        frequency=frequency,
        status=status,
    )
    db.add(kpi)
    db.commit()
    db.refresh(kpi)
    return kpi


def get_kpi(db: Session, kpi_id: int) -> PilotKPI | None:
    """KPI по id (или None)."""
    return db.get(PilotKPI, kpi_id)


def list_kpis(
    db: Session, workspace_id: int, *, status: str | None = None, limit: int = 200
) -> list[PilotKPI]:
    """KPI воркспейса (свежие сверху), опционально по статусу."""
    stmt = select(PilotKPI).where(PilotKPI.workspace_id == workspace_id)
    if status is not None:
        stmt = stmt.where(PilotKPI.status == status)
    stmt = stmt.order_by(PilotKPI.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_kpi(db: Session, kpi: PilotKPI, **fields: Any) -> PilotKPI:
    """Обновить поля KPI (только whitelist)."""
    for key, value in fields.items():
        if key in _KPI_FIELDS:
            setattr(kpi, key, value)
    db.commit()
    db.refresh(kpi)
    return kpi


# ---------------------------------------------------------------------------- #
# Feedback (v1.0.0, append-only)                                              #
# ---------------------------------------------------------------------------- #


def create_feedback(
    db: Session,
    *,
    workspace_id: int,
    decision: str,
    recommendation_id: int | None = None,
    comment: str | None = None,
    result: str | None = None,
) -> PilotFeedback:
    """Создать запись обратной связи (append-only)."""
    feedback = PilotFeedback(
        workspace_id=workspace_id,
        decision=decision,
        recommendation_id=recommendation_id,
        comment=comment,
        result=result,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def get_feedback(db: Session, feedback_id: int) -> PilotFeedback | None:
    """Обратная связь по id (или None)."""
    return db.get(PilotFeedback, feedback_id)


def list_feedback(db: Session, workspace_id: int, *, limit: int = 200) -> list[PilotFeedback]:
    """Обратная связь воркспейса (свежие сверху)."""
    stmt = (
        select(PilotFeedback)
        .where(PilotFeedback.workspace_id == workspace_id)
        .order_by(PilotFeedback.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_feedback(db: Session, feedback: PilotFeedback, **fields: Any) -> PilotFeedback:
    """Обновить поля обратной связи (только whitelist: comment/result)."""
    for key, value in fields.items():
        if key in _FEEDBACK_FIELDS:
            setattr(feedback, key, value)
    db.commit()
    db.refresh(feedback)
    return feedback


# ---------------------------------------------------------------------------- #
# Public views (v1.0.0)                                                       #
# ---------------------------------------------------------------------------- #


def public_goal_view(goal: PilotGoal) -> dict[str, Any]:
    """Безопасное представление цели (без секретов)."""
    return {
        "id": goal.id,
        "workspace_id": goal.workspace_id,
        "title": goal.title,
        "description": goal.description,
        "current_value": round(float(goal.current_value or 0.0), 2),
        "target_value": round(float(goal.target_value or 0.0), 2),
        "unit": goal.unit,
        "deadline": goal.deadline.isoformat() if goal.deadline else None,
        "priority": goal.priority,
        "status": goal.status,
        "created_at": goal.created_at.isoformat() if goal.created_at else None,
        "updated_at": goal.updated_at.isoformat() if goal.updated_at else None,
    }


def public_kpi_view(kpi: PilotKPI) -> dict[str, Any]:
    """Безопасное представление KPI (без секретов)."""
    return {
        "id": kpi.id,
        "workspace_id": kpi.workspace_id,
        "name": kpi.name,
        "current_value": round(float(kpi.current_value or 0.0), 2),
        "target_value": round(float(kpi.target_value or 0.0), 2),
        "unit": kpi.unit,
        "frequency": kpi.frequency,
        "status": kpi.status,
        "created_at": kpi.created_at.isoformat() if kpi.created_at else None,
        "updated_at": kpi.updated_at.isoformat() if kpi.updated_at else None,
    }


def public_feedback_view(feedback: PilotFeedback) -> dict[str, Any]:
    """Безопасное представление обратной связи (без секретов)."""
    return {
        "id": feedback.id,
        "workspace_id": feedback.workspace_id,
        "recommendation_id": feedback.recommendation_id,
        "decision": feedback.decision,
        "comment": feedback.comment,
        "result": feedback.result,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }
