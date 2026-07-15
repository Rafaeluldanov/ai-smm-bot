"""Репозиторий AI Workflow Manager (v0.7.2): процессы + этапы + блокеры.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business_workflow import BusinessWorkflow
from app.models.workflow_blocker import WorkflowBlocker
from app.models.workflow_step import WorkflowStep

# Поля процесса, которые можно обновлять (whitelist).
_WORKFLOW_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "description",
        "status",
        "goal",
        "target_value",
        "current_value",
        "start_date",
        "deadline",
        "progress_percent",
    }
)
# Этапы, которые считаются «в работе» (для health/прогресса).
_STEP_OPEN_STATUSES: tuple[str, ...] = ("pending", "assigned", "in_progress", "blocked")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Workflows                                                                    #
# ---------------------------------------------------------------------------- #


def create_workflow(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    name: str,
    workflow_type: str,
    description: str | None = None,
    goal: str | None = None,
    status: str = "draft",
    target_value: float = 0.0,
    current_value: float = 0.0,
    start_date: datetime | None = None,
    deadline: datetime | None = None,
    created_by_user_id: int | None = None,
    workflow_metadata: dict[str, Any] | None = None,
) -> BusinessWorkflow:
    """Создать бизнес-процесс (по умолчанию status=draft)."""
    workflow = BusinessWorkflow(
        project_id=project_id,
        account_id=account_id,
        name=name[:255],
        workflow_type=workflow_type,
        description=description,
        goal=goal,
        status=status,
        target_value=float(target_value or 0.0),
        current_value=float(current_value or 0.0),
        start_date=start_date,
        deadline=deadline,
        progress_percent=0.0,
        created_by_user_id=created_by_user_id,
        workflow_metadata=workflow_metadata or {},
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return workflow


def get_workflow(db: Session, workflow_id: int) -> BusinessWorkflow | None:
    """Процесс по id (или None)."""
    return db.get(BusinessWorkflow, workflow_id)


def list_workflows(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[BusinessWorkflow]:
    """Процессы проекта (свежие сверху), опционально по статусу."""
    stmt = select(BusinessWorkflow).where(BusinessWorkflow.project_id == project_id)
    if status is not None:
        stmt = stmt.where(BusinessWorkflow.status == status)
    stmt = stmt.order_by(BusinessWorkflow.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def get_active_workflows(
    db: Session, project_id: int, *, limit: int = 200
) -> list[BusinessWorkflow]:
    """Активные процессы проекта (status=active)."""
    return list_workflows(db, project_id, status="active", limit=limit)


def update_workflow(db: Session, workflow: BusinessWorkflow, **fields: Any) -> BusinessWorkflow:
    """Обновить поля процесса (только whitelist)."""
    for key, value in fields.items():
        if key in _WORKFLOW_FIELDS:
            setattr(workflow, key, value)
    db.commit()
    db.refresh(workflow)
    return workflow


# ---------------------------------------------------------------------------- #
# Steps                                                                        #
# ---------------------------------------------------------------------------- #


def create_step(
    db: Session,
    *,
    workflow_id: int,
    title: str,
    order_number: int = 0,
    description: str | None = None,
    status: str = "pending",
    priority: str = "medium",
    owner_user_id: int | None = None,
    deadline: datetime | None = None,
    step_metadata: dict[str, Any] | None = None,
) -> WorkflowStep:
    """Создать этап процесса (status=pending по умолчанию)."""
    step = WorkflowStep(
        workflow_id=workflow_id,
        title=title[:255],
        order_number=int(order_number or 0),
        description=description,
        status=status,
        priority=priority,
        owner_user_id=owner_user_id,
        deadline=deadline,
        progress_percent=0.0,
        step_metadata=step_metadata or {},
    )
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def get_step(db: Session, step_id: int) -> WorkflowStep | None:
    """Этап по id (или None)."""
    return db.get(WorkflowStep, step_id)


def list_steps(db: Session, workflow_id: int, *, limit: int = 500) -> list[WorkflowStep]:
    """Этапы процесса по порядку (order_number, затем id)."""
    stmt = (
        select(WorkflowStep)
        .where(WorkflowStep.workflow_id == workflow_id)
        .order_by(WorkflowStep.order_number.asc(), WorkflowStep.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


def next_order_number(db: Session, workflow_id: int) -> int:
    """Следующий порядковый номер этапа для процесса."""
    stmt = select(func.coalesce(func.max(WorkflowStep.order_number), 0)).where(
        WorkflowStep.workflow_id == workflow_id
    )
    return int(db.execute(stmt).scalar_one() or 0) + 1


def update_step_status(
    db: Session,
    step: WorkflowStep,
    status: str,
    *,
    progress_percent: float | None = None,
    stamp_completed: bool = False,
) -> WorkflowStep:
    """Сменить статус этапа (+прогресс/метка завершения)."""
    step.status = status
    if progress_percent is not None:
        step.progress_percent = max(0.0, min(100.0, float(progress_percent)))
    if stamp_completed:
        step.completed_at = _now()
        step.progress_percent = 100.0
    db.commit()
    db.refresh(step)
    return step


def assign_step(db: Session, step: WorkflowStep, *, owner_user_id: int | None) -> WorkflowStep:
    """Назначить ответственного за этап (status → assigned, если был pending)."""
    step.owner_user_id = owner_user_id
    if step.status == "pending":
        step.status = "assigned"
    db.commit()
    db.refresh(step)
    return step


# ---------------------------------------------------------------------------- #
# Blockers                                                                      #
# ---------------------------------------------------------------------------- #


def create_blocker(
    db: Session,
    *,
    workflow_id: int,
    blocker_type: str,
    title: str,
    step_id: int | None = None,
    description: str | None = None,
    severity: str = "medium",
) -> WorkflowBlocker:
    """Создать блокер процесса (status=open)."""
    blocker = WorkflowBlocker(
        workflow_id=workflow_id,
        step_id=step_id,
        blocker_type=blocker_type,
        title=title[:255],
        description=description,
        severity=severity,
        status="open",
    )
    db.add(blocker)
    db.commit()
    db.refresh(blocker)
    return blocker


def get_blocker(db: Session, blocker_id: int) -> WorkflowBlocker | None:
    """Блокер по id (или None)."""
    return db.get(WorkflowBlocker, blocker_id)


def list_blockers(
    db: Session, workflow_id: int, *, status: str | None = None, limit: int = 500
) -> list[WorkflowBlocker]:
    """Блокеры процесса (свежие сверху), опционально по статусу."""
    stmt = select(WorkflowBlocker).where(WorkflowBlocker.workflow_id == workflow_id)
    if status is not None:
        stmt = stmt.where(WorkflowBlocker.status == status)
    stmt = stmt.order_by(WorkflowBlocker.id.desc()).limit(max(1, min(limit, 2000)))
    return list(db.execute(stmt).scalars().all())


def resolve_blocker(db: Session, blocker: WorkflowBlocker) -> WorkflowBlocker:
    """Пометить блокер решённым (status=resolved, resolved_at)."""
    blocker.status = "resolved"
    blocker.resolved_at = _now()
    db.commit()
    db.refresh(blocker)
    return blocker


# ---------------------------------------------------------------------------- #
# Progress                                                                     #
# ---------------------------------------------------------------------------- #


def calculate_progress(db: Session, workflow: BusinessWorkflow) -> float:
    """Пересчитать прогресс процесса: completed / (все, кроме cancelled) × 100 → 0..100.

    Обновляет workflow.progress_percent (и completes процесс, если все этапы завершены).
    """
    steps = list_steps(db, workflow.id)
    relevant = [s for s in steps if s.status != "cancelled"]
    if not relevant:
        progress = 0.0
    else:
        completed = sum(1 for s in relevant if s.status == "completed")
        progress = round(100.0 * completed / len(relevant), 1)
    workflow.progress_percent = progress
    db.commit()
    db.refresh(workflow)
    return progress


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_workflow_view(workflow: BusinessWorkflow) -> dict[str, Any]:
    """Безопасное представление процесса (без секретов)."""
    return {
        "id": workflow.id,
        "project_id": workflow.project_id,
        "name": workflow.name,
        "description": workflow.description,
        "workflow_type": workflow.workflow_type,
        "status": workflow.status,
        "goal": workflow.goal,
        "target_value": round(float(workflow.target_value or 0.0), 2),
        "current_value": round(float(workflow.current_value or 0.0), 2),
        "progress_percent": round(float(workflow.progress_percent or 0.0), 1),
        "start_date": workflow.start_date.isoformat() if workflow.start_date else None,
        "deadline": workflow.deadline.isoformat() if workflow.deadline else None,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
    }


def public_step_view(step: WorkflowStep) -> dict[str, Any]:
    """Безопасное представление этапа."""
    return {
        "id": step.id,
        "workflow_id": step.workflow_id,
        "order_number": step.order_number,
        "title": step.title,
        "description": step.description,
        "status": step.status,
        "priority": step.priority,
        "owner_user_id": step.owner_user_id,
        "progress_percent": round(float(step.progress_percent or 0.0), 1),
        "deadline": step.deadline.isoformat() if step.deadline else None,
        "completed_at": step.completed_at.isoformat() if step.completed_at else None,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


def public_blocker_view(blocker: WorkflowBlocker) -> dict[str, Any]:
    """Безопасное представление блокера."""
    return {
        "id": blocker.id,
        "workflow_id": blocker.workflow_id,
        "step_id": blocker.step_id,
        "blocker_type": blocker.blocker_type,
        "title": blocker.title,
        "description": blocker.description,
        "severity": blocker.severity,
        "status": blocker.status,
        "resolved_at": blocker.resolved_at.isoformat() if blocker.resolved_at else None,
        "created_at": blocker.created_at.isoformat() if blocker.created_at else None,
    }


def build_workflow_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка процессов проекта: счётчики активных/открытых блокеров."""
    workflows = list_workflows(db, project_id)
    active = [w for w in workflows if w.status == "active"]
    open_blockers = 0
    for w in active:
        open_blockers += len(list_blockers(db, w.id, status="open"))
    return {
        "project_id": project_id,
        "workflows_total": len(workflows),
        "workflows_active": len(active),
        "blockers_open": open_blockers,
    }
