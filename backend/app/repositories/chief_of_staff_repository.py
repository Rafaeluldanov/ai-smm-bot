"""Репозиторий AI Chief of Staff (v0.7.1): брифинги + задачи владельца + память решений.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_business_task import AIBusinessTask
from app.models.business_decision_memory import KEY_MAX_LENGTH, BusinessDecisionMemory
from app.models.executive_briefing import ExecutiveBriefing

# Открытые (ещё не терминальные) статусы задачи — единый источник для reassign/сводки.
_OPEN_TASK_STATUSES: tuple[str, ...] = ("suggested", "accepted")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Executive briefings                                                          #
# ---------------------------------------------------------------------------- #


def create_briefing(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    type: str,
    title: str,
    summary: str | None = None,
    business_state: dict[str, Any] | None = None,
    key_changes: list[Any] | None = None,
    risks: list[Any] | None = None,
    opportunities: list[Any] | None = None,
    recommended_actions: list[Any] | None = None,
    confidence_score: float = 0.0,
) -> ExecutiveBriefing:
    """Создать брифинг (status=generated, отметка времени generated_at)."""
    briefing = ExecutiveBriefing(
        project_id=project_id,
        account_id=account_id,
        type=type,
        status="generated",
        title=title[:255],
        summary=summary,
        business_state=business_state or {},
        key_changes=key_changes or [],
        risks=risks or [],
        opportunities=opportunities or [],
        recommended_actions=recommended_actions or [],
        confidence_score=float(confidence_score or 0.0),
        generated_at=_now(),
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    return briefing


def get_briefing(db: Session, briefing_id: int) -> ExecutiveBriefing | None:
    """Брифинг по id (или None)."""
    return db.get(ExecutiveBriefing, briefing_id)


def get_latest_briefing(
    db: Session, project_id: int, *, type: str | None = None
) -> ExecutiveBriefing | None:
    """Последний брифинг проекта (опционально заданного типа)."""
    stmt = select(ExecutiveBriefing).where(ExecutiveBriefing.project_id == project_id)
    if type is not None:
        stmt = stmt.where(ExecutiveBriefing.type == type)
    stmt = stmt.order_by(ExecutiveBriefing.id.desc())
    return db.execute(stmt).scalars().first()


def list_briefings(
    db: Session, project_id: int, *, type: str | None = None, limit: int = 50
) -> list[ExecutiveBriefing]:
    """Брифинги проекта (свежие сверху)."""
    stmt = select(ExecutiveBriefing).where(ExecutiveBriefing.project_id == project_id)
    if type is not None:
        stmt = stmt.where(ExecutiveBriefing.type == type)
    stmt = stmt.order_by(ExecutiveBriefing.id.desc()).limit(max(1, min(limit, 500)))
    return list(db.execute(stmt).scalars().all())


def mark_viewed(db: Session, briefing: ExecutiveBriefing) -> ExecutiveBriefing:
    """Отметить брифинг просмотренным (status=viewed, viewed_at)."""
    if briefing.status == "generated":
        briefing.status = "viewed"
    if briefing.viewed_at is None:
        briefing.viewed_at = _now()
    db.commit()
    db.refresh(briefing)
    return briefing


# ---------------------------------------------------------------------------- #
# Owner tasks                                                                  #
# ---------------------------------------------------------------------------- #


def create_task(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    briefing_id: int | None,
    task_type: str,
    title: str,
    priority: str = "medium",
    priority_score: float = 0.0,
    description: str | None = None,
    reasoning: list[Any] | None = None,
    expected_impact: dict[str, Any] | None = None,
    source_modules: list[Any] | None = None,
) -> AIBusinessTask:
    """Создать задачу владельца (status=suggested)."""
    task = AIBusinessTask(
        project_id=project_id,
        account_id=account_id,
        briefing_id=briefing_id,
        task_type=task_type,
        priority=priority,
        priority_score=float(priority_score or 0.0),
        status="suggested",
        title=title[:255],
        description=description,
        reasoning=reasoning or [],
        expected_impact=expected_impact or {},
        source_modules=source_modules or [],
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, task_id: int) -> AIBusinessTask | None:
    """Задача по id (или None)."""
    return db.get(AIBusinessTask, task_id)


def list_tasks(
    db: Session,
    project_id: int,
    *,
    status: str | None = None,
    briefing_id: int | None = None,
    limit: int = 200,
) -> list[AIBusinessTask]:
    """Задачи проекта (по убыванию приоритетного score), с фильтрами."""
    stmt = select(AIBusinessTask).where(AIBusinessTask.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AIBusinessTask.status == status)
    if briefing_id is not None:
        stmt = stmt.where(AIBusinessTask.briefing_id == briefing_id)
    stmt = stmt.order_by(AIBusinessTask.priority_score.desc(), AIBusinessTask.id.desc()).limit(
        max(1, min(limit, 1000))
    )
    return list(db.execute(stmt).scalars().all())


def accept_task(db: Session, task: AIBusinessTask, *, user_id: int | None = None) -> AIBusinessTask:
    """Одобрить задачу (status=accepted). НЕ выполняет действие."""
    task.status = "accepted"
    task.accepted_by_user_id = user_id
    db.commit()
    db.refresh(task)
    return task


def reject_task(db: Session, task: AIBusinessTask) -> AIBusinessTask:
    """Отклонить задачу (status=rejected)."""
    task.status = "rejected"
    db.commit()
    db.refresh(task)
    return task


def complete_task(db: Session, task: AIBusinessTask) -> AIBusinessTask:
    """Зафиксировать выполнение задачи владельцем (status=completed). Внешних действий нет."""
    task.status = "completed"
    task.completed_at = _now()
    db.commit()
    db.refresh(task)
    return task


def list_open_tasks(db: Session, project_id: int) -> list[AIBusinessTask]:
    """Открытые (suggested/accepted) задачи проекта по убыванию приоритета."""
    stmt = (
        select(AIBusinessTask)
        .where(AIBusinessTask.project_id == project_id)
        .where(AIBusinessTask.status.in_(_OPEN_TASK_STATUSES))
        .order_by(AIBusinessTask.priority_score.desc(), AIBusinessTask.id.desc())
    )
    return list(db.execute(stmt).scalars().all())


def reassign_open_tasks_to_briefing(
    db: Session, project_id: int, briefing_id: int
) -> list[AIBusinessTask]:
    """Привязать открытые (suggested/accepted) задачи проекта к новому брифингу.

    Терминальные (completed/rejected) остаются за своими историческими брифингами.
    Возвращает открытые задачи проекта по убыванию приоритета — актуальный набор брифинга.
    """
    tasks = list_open_tasks(db, project_id)
    for task in tasks:
        task.briefing_id = briefing_id
    db.commit()
    return tasks


# ---------------------------------------------------------------------------- #
# Decision memory                                                              #
# ---------------------------------------------------------------------------- #


def save_decision(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    decision_type: str,
    key: str,
    value: dict[str, Any] | None = None,
    reason: str | None = None,
    user_id: int | None = None,
) -> BusinessDecisionMemory:
    """Сохранить решение владельца (одна активная запись на key — обновляем существующую)."""
    # Обрезаем ДО поиска: столбец key = String(KEY_MAX_LENGTH), иначе длинный key искали бы
    # полным, а хранили обрезанным → «одна активная запись на key» нарушалась бы.
    key = key[:KEY_MAX_LENGTH]
    existing = get_active_decision_by_key(db, project_id, key)
    if existing is not None:
        return _update_active_decision(
            db, existing, decision_type, value, reason, user_id
        )
    decision = BusinessDecisionMemory(
        project_id=project_id,
        account_id=account_id,
        decision_type=decision_type,
        key=key,
        value=value or {},
        reason=reason,
        created_by_user_id=user_id,
        active=True,
    )
    db.add(decision)
    try:
        db.commit()
    except IntegrityError:
        # Гонка: другой запрос уже создал активную запись для того же (project_id, key)
        # (частичный уникальный индекс uq_business_decision_active_key). Мягко обновляем её.
        db.rollback()
        existing = get_active_decision_by_key(db, project_id, key)
        if existing is None:
            raise
        return _update_active_decision(db, existing, decision_type, value, reason, user_id)
    db.refresh(decision)
    return decision


def _update_active_decision(
    db: Session,
    decision: BusinessDecisionMemory,
    decision_type: str,
    value: dict[str, Any] | None,
    reason: str | None,
    user_id: int | None,
) -> BusinessDecisionMemory:
    """Обновить существующую активную запись решения (общий путь для update и гонки)."""
    decision.decision_type = decision_type
    decision.value = value or {}
    decision.reason = reason
    decision.created_by_user_id = user_id
    decision.active = True
    db.commit()
    db.refresh(decision)
    return decision


def get_decision(db: Session, decision_id: int) -> BusinessDecisionMemory | None:
    """Решение по id (или None)."""
    return db.get(BusinessDecisionMemory, decision_id)


def get_active_decision_by_key(
    db: Session, project_id: int, key: str
) -> BusinessDecisionMemory | None:
    """Активное решение проекта по семантическому ключу (или None)."""
    stmt = (
        select(BusinessDecisionMemory)
        .where(BusinessDecisionMemory.project_id == project_id)
        .where(BusinessDecisionMemory.key == key)
        .where(BusinessDecisionMemory.active.is_(True))
        .order_by(BusinessDecisionMemory.id.desc())
    )
    return db.execute(stmt).scalars().first()


def get_decisions(
    db: Session,
    project_id: int,
    *,
    active_only: bool = True,
    decision_type: str | None = None,
    limit: int = 200,
) -> list[BusinessDecisionMemory]:
    """Решения владельца проекта (по умолчанию только активные)."""
    stmt = select(BusinessDecisionMemory).where(BusinessDecisionMemory.project_id == project_id)
    if active_only:
        stmt = stmt.where(BusinessDecisionMemory.active.is_(True))
    if decision_type is not None:
        stmt = stmt.where(BusinessDecisionMemory.decision_type == decision_type)
    stmt = stmt.order_by(BusinessDecisionMemory.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def disable_decision(db: Session, decision: BusinessDecisionMemory) -> BusinessDecisionMemory:
    """Деактивировать решение (active=False). Запись не удаляется (история сохраняется)."""
    decision.active = False
    db.commit()
    db.refresh(decision)
    return decision


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_briefing_view(briefing: ExecutiveBriefing) -> dict[str, Any]:
    """Безопасное представление брифинга (без секретов)."""
    return {
        "id": briefing.id,
        "project_id": briefing.project_id,
        "type": briefing.type,
        "status": briefing.status,
        "title": briefing.title,
        "summary": briefing.summary,
        "business_state": dict(briefing.business_state or {}),
        "key_changes": list(briefing.key_changes or []),
        "risks": list(briefing.risks or []),
        "opportunities": list(briefing.opportunities or []),
        "recommended_actions": list(briefing.recommended_actions or []),
        "confidence_score": round(float(briefing.confidence_score or 0.0), 1),
        "generated_at": briefing.generated_at.isoformat() if briefing.generated_at else None,
        "viewed_at": briefing.viewed_at.isoformat() if briefing.viewed_at else None,
        "created_at": briefing.created_at.isoformat() if briefing.created_at else None,
    }


def public_task_view(task: AIBusinessTask) -> dict[str, Any]:
    """Безопасное представление задачи владельца."""
    return {
        "id": task.id,
        "project_id": task.project_id,
        "briefing_id": task.briefing_id,
        "task_type": task.task_type,
        "priority": task.priority,
        "priority_score": round(float(task.priority_score or 0.0), 1),
        "status": task.status,
        "title": task.title,
        "description": task.description,
        "reasoning": list(task.reasoning or []),
        "expected_impact": dict(task.expected_impact or {}),
        "source_modules": list(task.source_modules or []),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def public_decision_view(decision: BusinessDecisionMemory) -> dict[str, Any]:
    """Безопасное представление решения владельца."""
    return {
        "id": decision.id,
        "project_id": decision.project_id,
        "decision_type": decision.decision_type,
        "key": decision.key,
        "value": dict(decision.value or {}),
        "reason": decision.reason,
        "active": bool(decision.active),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def build_chief_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка ассистента: последний брифинг + счётчики задач/решений."""
    briefing = get_latest_briefing(db, project_id)
    open_tasks = list_tasks(db, project_id, status="suggested")
    return {
        "project_id": project_id,
        "has_briefing": briefing is not None,
        "latest_briefing": public_briefing_view(briefing) if briefing is not None else None,
        "tasks_suggested": len(open_tasks),
        "decisions_active": len(get_decisions(db, project_id, active_only=True)),
    }
