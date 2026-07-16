"""Репозиторий AI Continuous Improvement (v0.8.0): опыт + события + паттерны + улучшения.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
Learning-слой: только учится и советует; бизнес/стратегию/KPI не меняет.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_pattern import AIPattern
from app.models.experience_memory import ExperienceMemory
from app.models.improvement_item import ImprovementItem
from app.models.learning_event import LearningEvent

# Поля улучшения, которые можно обновлять (whitelist).
_IMPROVEMENT_FIELDS: frozenset[str] = frozenset(
    {"status", "priority", "title", "description", "expected_impact"}
)


# ---------------------------------------------------------------------------- #
# Experiences                                                                  #
# ---------------------------------------------------------------------------- #


def create_experience(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    experience_type: str,
    title: str,
    source_id: int | None = None,
    context: dict[str, Any] | None = None,
    expected_result: dict[str, Any] | None = None,
    actual_result: dict[str, Any] | None = None,
    outcome: str = "neutral",
    lessons: list[Any] | None = None,
    confidence_score: float = 0.0,
) -> ExperienceMemory:
    """Создать единицу опыта."""
    experience = ExperienceMemory(
        project_id=project_id,
        account_id=account_id,
        experience_type=experience_type,
        title=title[:255],
        source_id=source_id,
        context=context or {},
        expected_result=expected_result or {},
        actual_result=actual_result or {},
        outcome=outcome,
        lessons=lessons or [],
        confidence_score=float(confidence_score or 0.0),
    )
    db.add(experience)
    db.commit()
    db.refresh(experience)
    return experience


def get_experience(db: Session, experience_id: int) -> ExperienceMemory | None:
    """Опыт по id (или None)."""
    return db.get(ExperienceMemory, experience_id)


def get_experience_history(
    db: Session, project_id: int, *, experience_type: str | None = None, limit: int = 200
) -> list[ExperienceMemory]:
    """История опыта проекта (свежие сверху), опционально по типу."""
    stmt = select(ExperienceMemory).where(ExperienceMemory.project_id == project_id)
    if experience_type is not None:
        stmt = stmt.where(ExperienceMemory.experience_type == experience_type)
    stmt = stmt.order_by(ExperienceMemory.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Learning events                                                              #
# ---------------------------------------------------------------------------- #


def create_event(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    event_type: str,
    title: str,
    experience_id: int | None = None,
    description: str | None = None,
    impact: dict[str, Any] | None = None,
) -> LearningEvent:
    """Создать событие обучения (append-only)."""
    event = LearningEvent(
        project_id=project_id,
        account_id=account_id,
        event_type=event_type,
        title=title[:255],
        experience_id=experience_id,
        description=description,
        impact=impact or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_events(db: Session, project_id: int, *, limit: int = 200) -> list[LearningEvent]:
    """События обучения проекта (свежие сверху)."""
    stmt = (
        select(LearningEvent)
        .where(LearningEvent.project_id == project_id)
        .order_by(LearningEvent.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Patterns                                                                     #
# ---------------------------------------------------------------------------- #


def create_pattern(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    pattern_type: str,
    title: str,
    description: str | None = None,
    signals: list[Any] | None = None,
    confidence_score: float = 0.0,
) -> AIPattern:
    """Создать AI-паттерн."""
    pattern = AIPattern(
        project_id=project_id,
        account_id=account_id,
        pattern_type=pattern_type,
        title=title[:255],
        description=description,
        signals=signals or [],
        confidence_score=float(confidence_score or 0.0),
    )
    db.add(pattern)
    db.commit()
    db.refresh(pattern)
    return pattern


def get_pattern(db: Session, pattern_id: int) -> AIPattern | None:
    """Паттерн по id (или None)."""
    return db.get(AIPattern, pattern_id)


def list_patterns(
    db: Session, project_id: int, *, pattern_type: str | None = None, limit: int = 200
) -> list[AIPattern]:
    """Паттерны проекта (свежие сверху), опционально по типу."""
    stmt = select(AIPattern).where(AIPattern.project_id == project_id)
    if pattern_type is not None:
        stmt = stmt.where(AIPattern.pattern_type == pattern_type)
    stmt = stmt.order_by(AIPattern.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Improvements                                                                 #
# ---------------------------------------------------------------------------- #


def create_improvement(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    title: str,
    pattern_id: int | None = None,
    status: str = "identified",
    priority: str = "medium",
    description: str | None = None,
    expected_impact: dict[str, Any] | None = None,
) -> ImprovementItem:
    """Создать элемент backlog улучшений (status=identified по умолчанию)."""
    improvement = ImprovementItem(
        project_id=project_id,
        account_id=account_id,
        title=title[:255],
        pattern_id=pattern_id,
        status=status,
        priority=priority,
        description=description,
        expected_impact=expected_impact or {},
    )
    db.add(improvement)
    db.commit()
    db.refresh(improvement)
    return improvement


def get_improvement(db: Session, improvement_id: int) -> ImprovementItem | None:
    """Улучшение по id (или None)."""
    return db.get(ImprovementItem, improvement_id)


def list_improvements(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[ImprovementItem]:
    """Улучшения проекта (свежие сверху), опционально по статусу."""
    stmt = select(ImprovementItem).where(ImprovementItem.project_id == project_id)
    if status is not None:
        stmt = stmt.where(ImprovementItem.status == status)
    stmt = stmt.order_by(ImprovementItem.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def update_improvement(db: Session, improvement: ImprovementItem, **fields: Any) -> ImprovementItem:
    """Обновить поля улучшения (только whitelist)."""
    for key, value in fields.items():
        if key in _IMPROVEMENT_FIELDS:
            setattr(improvement, key, value)
    db.commit()
    db.refresh(improvement)
    return improvement


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_experience_view(experience: ExperienceMemory) -> dict[str, Any]:
    """Безопасное представление опыта (без секретов)."""
    return {
        "id": experience.id,
        "project_id": experience.project_id,
        "experience_type": experience.experience_type,
        "source_id": experience.source_id,
        "title": experience.title,
        "context": dict(experience.context or {}),
        "expected_result": dict(experience.expected_result or {}),
        "actual_result": dict(experience.actual_result or {}),
        "outcome": experience.outcome,
        "lessons": list(experience.lessons or []),
        "confidence_score": round(float(experience.confidence_score or 0.0), 1),
        "created_at": experience.created_at.isoformat() if experience.created_at else None,
        "updated_at": experience.updated_at.isoformat() if experience.updated_at else None,
    }


def public_event_view(event: LearningEvent) -> dict[str, Any]:
    """Безопасное представление события обучения."""
    return {
        "id": event.id,
        "project_id": event.project_id,
        "event_type": event.event_type,
        "experience_id": event.experience_id,
        "title": event.title,
        "description": event.description,
        "impact": dict(event.impact or {}),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def public_pattern_view(pattern: AIPattern) -> dict[str, Any]:
    """Безопасное представление паттерна."""
    return {
        "id": pattern.id,
        "project_id": pattern.project_id,
        "pattern_type": pattern.pattern_type,
        "title": pattern.title,
        "description": pattern.description,
        "signals": list(pattern.signals or []),
        "confidence_score": round(float(pattern.confidence_score or 0.0), 1),
        "created_at": pattern.created_at.isoformat() if pattern.created_at else None,
        "updated_at": pattern.updated_at.isoformat() if pattern.updated_at else None,
    }


def public_improvement_view(improvement: ImprovementItem) -> dict[str, Any]:
    """Безопасное представление улучшения."""
    return {
        "id": improvement.id,
        "project_id": improvement.project_id,
        "pattern_id": improvement.pattern_id,
        "status": improvement.status,
        "priority": improvement.priority,
        "title": improvement.title,
        "description": improvement.description,
        "expected_impact": dict(improvement.expected_impact or {}),
        "created_at": improvement.created_at.isoformat() if improvement.created_at else None,
        "updated_at": improvement.updated_at.isoformat() if improvement.updated_at else None,
    }


def build_learning_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Continuous Improvement: счётчики опыта/паттернов/улучшений."""
    experiences = get_experience_history(db, project_id)
    patterns = list_patterns(db, project_id)
    improvements = list_improvements(db, project_id)
    open_items = sum(1 for i in improvements if i.status in ("identified", "reviewed"))
    return {
        "project_id": project_id,
        "experiences_total": len(experiences),
        "patterns_total": len(patterns),
        "improvements_total": len(improvements),
        "improvements_open": open_items,
    }
