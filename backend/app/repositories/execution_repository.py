"""Репозиторий AI Execution Coordinator (v0.7.8): планы + цели + задачи + зависимости.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Coordination-слой: НЕ выполняет задачи; статусы/владельцы меняет владелец/AI-совет.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.execution_dependency import ExecutionDependency
from app.models.execution_objective import ExecutionObjective
from app.models.execution_plan import ExecutionPlan
from app.models.execution_task import ExecutionTask

# Поля, которые можно обновлять (whitelist).
_PLAN_FIELDS: frozenset[str] = frozenset(
    {"status", "title", "description", "progress_percent", "start_date", "deadline"}
)
_OBJECTIVE_FIELDS: frozenset[str] = frozenset(
    {"status", "title", "description", "kpi", "priority", "progress_percent", "owner_user_id"}
)
_TASK_FIELDS: frozenset[str] = frozenset(
    {"status", "title", "description", "priority", "owner_user_id", "deadline", "progress_percent"}
)


# ---------------------------------------------------------------------------- #
# Execution plans                                                              #
# ---------------------------------------------------------------------------- #


def create_execution_plan(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    title: str,
    strategic_plan_id: int | None = None,
    description: str | None = None,
    status: str = "draft",
    start_date: datetime | None = None,
    deadline: datetime | None = None,
    plan_metadata: dict[str, Any] | None = None,
) -> ExecutionPlan:
    """Создать план исполнения (status=draft по умолчанию)."""
    plan = ExecutionPlan(
        project_id=project_id,
        account_id=account_id,
        strategic_plan_id=strategic_plan_id,
        title=title[:255],
        description=description,
        status=status,
        start_date=start_date,
        deadline=deadline,
        plan_metadata=plan_metadata or {},
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_execution_plan(db: Session, plan_id: int) -> ExecutionPlan | None:
    """План исполнения по id (или None)."""
    return db.get(ExecutionPlan, plan_id)


def list_execution_plans(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[ExecutionPlan]:
    """Планы исполнения проекта (свежие сверху), опционально по статусу."""
    stmt = select(ExecutionPlan).where(ExecutionPlan.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ExecutionPlan.status == status)
    stmt = stmt.order_by(ExecutionPlan.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_execution_plan(db: Session, plan: ExecutionPlan, **fields: Any) -> ExecutionPlan:
    """Обновить поля плана исполнения (только whitelist)."""
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
    execution_plan_id: int,
    title: str,
    description: str | None = None,
    kpi: list[Any] | None = None,
    priority: str = "medium",
    status: str = "active",
    owner_user_id: int | None = None,
) -> ExecutionObjective:
    """Создать цель исполнения."""
    objective = ExecutionObjective(
        execution_plan_id=execution_plan_id,
        title=title[:255],
        description=description,
        kpi=kpi or [],
        priority=priority,
        status=status,
        owner_user_id=owner_user_id,
    )
    db.add(objective)
    db.commit()
    db.refresh(objective)
    return objective


def get_objective(db: Session, objective_id: int) -> ExecutionObjective | None:
    """Цель исполнения по id (или None)."""
    return db.get(ExecutionObjective, objective_id)


def list_objectives(
    db: Session, execution_plan_id: int, *, limit: int = 200
) -> list[ExecutionObjective]:
    """Цели плана исполнения (по порядку создания)."""
    stmt = (
        select(ExecutionObjective)
        .where(ExecutionObjective.execution_plan_id == execution_plan_id)
        .order_by(ExecutionObjective.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_objective(
    db: Session, objective: ExecutionObjective, **fields: Any
) -> ExecutionObjective:
    """Обновить поля цели исполнения (только whitelist)."""
    for key, value in fields.items():
        if key in _OBJECTIVE_FIELDS:
            setattr(objective, key, value)
    db.commit()
    db.refresh(objective)
    return objective


# ---------------------------------------------------------------------------- #
# Tasks                                                                        #
# ---------------------------------------------------------------------------- #


def create_task(
    db: Session,
    *,
    objective_id: int,
    title: str,
    description: str | None = None,
    priority: str = "medium",
    status: str = "pending",
    owner_user_id: int | None = None,
    deadline: datetime | None = None,
    task_metadata: dict[str, Any] | None = None,
) -> ExecutionTask:
    """Создать задачу исполнения (status=pending по умолчанию)."""
    task = ExecutionTask(
        objective_id=objective_id,
        title=title[:255],
        description=description,
        priority=priority,
        status=status,
        owner_user_id=owner_user_id,
        deadline=deadline,
        task_metadata=task_metadata or {},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> ExecutionTask | None:
    """Задача исполнения по id (или None)."""
    return db.get(ExecutionTask, task_id)


def list_tasks(db: Session, objective_id: int, *, limit: int = 500) -> list[ExecutionTask]:
    """Задачи цели исполнения (по порядку создания)."""
    stmt = (
        select(ExecutionTask)
        .where(ExecutionTask.objective_id == objective_id)
        .order_by(ExecutionTask.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


def list_tasks_for_plan(db: Session, execution_plan_id: int) -> list[ExecutionTask]:
    """Все задачи плана исполнения (по всем целям, по порядку создания)."""
    stmt = (
        select(ExecutionTask)
        .join(ExecutionObjective, ExecutionTask.objective_id == ExecutionObjective.id)
        .where(ExecutionObjective.execution_plan_id == execution_plan_id)
        .order_by(ExecutionTask.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def update_task(db: Session, task: ExecutionTask, **fields: Any) -> ExecutionTask:
    """Обновить поля задачи исполнения (только whitelist)."""
    for key, value in fields.items():
        if key in _TASK_FIELDS:
            setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


def update_task_status(db: Session, task: ExecutionTask, status: str) -> ExecutionTask:
    """Сменить статус задачи (+синхронизировать прогресс completed/pending)."""
    task.status = status
    if status == "completed":
        task.progress_percent = 100.0
    elif status in ("pending", "cancelled"):
        task.progress_percent = 0.0
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------- #
# Dependencies                                                                 #
# ---------------------------------------------------------------------------- #


def create_dependency(
    db: Session,
    *,
    task_id: int,
    depends_on_task_id: int | None = None,
    dependency_type: str = "task",
    status: str = "pending",
) -> ExecutionDependency:
    """Создать зависимость задачи (append-only)."""
    dependency = ExecutionDependency(
        task_id=task_id,
        depends_on_task_id=depends_on_task_id,
        dependency_type=dependency_type,
        status=status,
    )
    db.add(dependency)
    db.commit()
    db.refresh(dependency)
    return dependency


def list_dependencies(db: Session, task_id: int, *, limit: int = 200) -> list[ExecutionDependency]:
    """Зависимости задачи (по порядку создания)."""
    stmt = (
        select(ExecutionDependency)
        .where(ExecutionDependency.task_id == task_id)
        .order_by(ExecutionDependency.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Progress / blockers                                                          #
# ---------------------------------------------------------------------------- #


def calculate_progress(db: Session, execution_plan_id: int) -> float:
    """Прогресс плана = completed tasks / all tasks × 100 (0..100)."""
    tasks = list_tasks_for_plan(db, execution_plan_id)
    active = [t for t in tasks if t.status != "cancelled"]
    if not active:
        return 0.0
    completed = sum(1 for t in active if t.status == "completed")
    return round(completed / len(active) * 100.0, 1)


def get_blocked_tasks(db: Session, execution_plan_id: int) -> list[ExecutionTask]:
    """Явно заблокированные задачи плана (status=blocked)."""
    return [t for t in list_tasks_for_plan(db, execution_plan_id) if t.status == "blocked"]


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_plan_view(plan: ExecutionPlan) -> dict[str, Any]:
    """Безопасное представление плана исполнения (без секретов)."""
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "strategic_plan_id": plan.strategic_plan_id,
        "status": plan.status,
        "title": plan.title,
        "description": plan.description,
        "progress_percent": round(float(plan.progress_percent or 0.0), 1),
        "start_date": plan.start_date.isoformat() if plan.start_date else None,
        "deadline": plan.deadline.isoformat() if plan.deadline else None,
        "metadata": dict(plan.plan_metadata or {}),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def public_objective_view(objective: ExecutionObjective) -> dict[str, Any]:
    """Безопасное представление цели исполнения."""
    return {
        "id": objective.id,
        "execution_plan_id": objective.execution_plan_id,
        "title": objective.title,
        "description": objective.description,
        "kpi": list(objective.kpi or []),
        "priority": objective.priority,
        "status": objective.status,
        "progress_percent": round(float(objective.progress_percent or 0.0), 1),
        "owner_user_id": objective.owner_user_id,
        "created_at": objective.created_at.isoformat() if objective.created_at else None,
        "updated_at": objective.updated_at.isoformat() if objective.updated_at else None,
    }


def public_task_view(task: ExecutionTask) -> dict[str, Any]:
    """Безопасное представление задачи исполнения."""
    return {
        "id": task.id,
        "objective_id": task.objective_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "owner_user_id": task.owner_user_id,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "progress_percent": round(float(task.progress_percent or 0.0), 1),
        "metadata": dict(task.task_metadata or {}),
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }


def public_dependency_view(dependency: ExecutionDependency) -> dict[str, Any]:
    """Безопасное представление зависимости."""
    return {
        "id": dependency.id,
        "task_id": dependency.task_id,
        "depends_on_task_id": dependency.depends_on_task_id,
        "dependency_type": dependency.dependency_type,
        "status": dependency.status,
        "created_at": dependency.created_at.isoformat() if dependency.created_at else None,
    }


def build_execution_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Execution Coordinator: счётчики планов по ключевым статусам."""
    plans = list_execution_plans(db, project_id)
    active = sum(1 for p in plans if p.status == "active")
    completed = sum(1 for p in plans if p.status == "completed")
    return {
        "project_id": project_id,
        "plans_total": len(plans),
        "plans_active": active,
        "plans_completed": completed,
    }
