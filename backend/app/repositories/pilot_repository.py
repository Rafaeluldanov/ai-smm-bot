"""Репозиторий AI Business OS Pilot (v0.9.1): pilot-воркспейсы + бизнес-профили.

Публичные представления без секретов/токенов. Tenant isolation — list по account_id + проверка на
сервис/API-слое. PILOT/advisory-слой: только описание пилота; бизнес/CRM не затрагивает.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pilot_business_profile import PilotBusinessProfile
from app.models.pilot_workspace import PilotWorkspace

# Поля, которые можно обновлять (whitelist).
_WORKSPACE_FIELDS: frozenset[str] = frozenset({"company_name", "industry", "status"})
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
