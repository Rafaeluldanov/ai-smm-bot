"""Репозиторий AI Business OS MVP Testing (v0.9.0): demo-воркспейсы + demo-сценарии.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
DEMO/testing-слой: только тестовые сущности прогонов; реального бизнеса/CRM не затрагивает.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.demo_scenario import DemoScenario
from app.models.demo_workspace import DemoWorkspace

# Поля сценария, которые можно обновлять (whitelist).
_SCENARIO_FIELDS: frozenset[str] = frozenset({"status", "input_data", "result_data", "score"})


# ---------------------------------------------------------------------------- #
# Workspaces                                                                   #
# ---------------------------------------------------------------------------- #


def create_workspace(
    db: Session,
    *,
    account_id: int | None,
    name: str,
    company_name: str = "",
    industry: str = "",
    description: str | None = None,
) -> DemoWorkspace:
    """Создать demo-воркспейс."""
    workspace = DemoWorkspace(
        account_id=account_id,
        name=name[:255],
        company_name=company_name[:255],
        industry=industry[:100],
        description=description,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def get_workspace(db: Session, workspace_id: int) -> DemoWorkspace | None:
    """Воркспейс по id (или None)."""
    return db.get(DemoWorkspace, workspace_id)


def list_workspaces(
    db: Session, *, account_id: int | None = None, limit: int = 200
) -> list[DemoWorkspace]:
    """Demo-воркспейсы (свежие сверху), опционально по аккаунту."""
    stmt = select(DemoWorkspace)
    if account_id is not None:
        stmt = stmt.where(DemoWorkspace.account_id == account_id)
    stmt = stmt.order_by(DemoWorkspace.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Scenarios                                                                    #
# ---------------------------------------------------------------------------- #


def create_scenario(
    db: Session,
    *,
    workspace_id: int,
    scenario_type: str,
    status: str = "draft",
    input_data: dict[str, Any] | None = None,
    result_data: dict[str, Any] | None = None,
    score: float = 0.0,
) -> DemoScenario:
    """Создать demo-сценарий."""
    scenario = DemoScenario(
        workspace_id=workspace_id,
        scenario_type=scenario_type,
        status=status,
        input_data=input_data or {},
        result_data=result_data or {},
        score=float(score or 0.0),
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


def get_scenario(db: Session, scenario_id: int) -> DemoScenario | None:
    """Сценарий по id (или None)."""
    return db.get(DemoScenario, scenario_id)


def save_result(
    db: Session,
    scenario: DemoScenario,
    *,
    status: str,
    result_data: dict[str, Any],
    score: float,
) -> DemoScenario:
    """Сохранить итог прогона сценария (статус + результат + score)."""
    scenario.status = status
    scenario.result_data = result_data
    scenario.score = float(score or 0.0)
    db.commit()
    db.refresh(scenario)
    return scenario


def update_scenario(db: Session, scenario: DemoScenario, **fields: Any) -> DemoScenario:
    """Обновить поля сценария (только whitelist)."""
    for key, value in fields.items():
        if key in _SCENARIO_FIELDS:
            setattr(scenario, key, value)
    db.commit()
    db.refresh(scenario)
    return scenario


def list_scenarios(
    db: Session, *, workspace_id: int | None = None, status: str | None = None, limit: int = 200
) -> list[DemoScenario]:
    """Demo-сценарии (свежие сверху), опционально по воркспейсу/статусу."""
    stmt = select(DemoScenario)
    if workspace_id is not None:
        stmt = stmt.where(DemoScenario.workspace_id == workspace_id)
    if status is not None:
        stmt = stmt.where(DemoScenario.status == status)
    stmt = stmt.order_by(DemoScenario.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def list_scenarios_for_account(
    db: Session, account_id: int, *, limit: int = 200
) -> list[DemoScenario]:
    """Все demo-сценарии аккаунта (join через workspace), свежие сверху."""
    stmt = (
        select(DemoScenario)
        .join(DemoWorkspace, DemoScenario.workspace_id == DemoWorkspace.id)
        .where(DemoWorkspace.account_id == account_id)
        .order_by(DemoScenario.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_workspace_view(workspace: DemoWorkspace) -> dict[str, Any]:
    """Безопасное представление воркспейса (без секретов)."""
    return {
        "id": workspace.id,
        "account_id": workspace.account_id,
        "name": workspace.name,
        "company_name": workspace.company_name,
        "industry": workspace.industry,
        "description": workspace.description,
        "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
    }


def public_scenario_view(scenario: DemoScenario) -> dict[str, Any]:
    """Безопасное представление сценария (без секретов)."""
    return {
        "id": scenario.id,
        "workspace_id": scenario.workspace_id,
        "scenario_type": scenario.scenario_type,
        "status": scenario.status,
        "input_data": dict(scenario.input_data or {}),
        "result_data": dict(scenario.result_data or {}),
        "score": round(float(scenario.score or 0.0), 1),
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
        "updated_at": scenario.updated_at.isoformat() if scenario.updated_at else None,
    }
