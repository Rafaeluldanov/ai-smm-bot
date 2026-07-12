"""Репозиторий предложений экспериментов (experiment_suggestions).

``recommendation_payload``/``source_signals`` секретов не содержат (обеспечивает сервисный
слой). Все выборки фильтруют по ``project_id``/``account_id`` (изоляция — на API/сервисном
слое).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.experiment_suggestion import (
    ACTIVE_SUGGESTION_STATUSES,
    ExperimentSuggestion,
)

_ACTIVE_STATUSES = ACTIVE_SUGGESTION_STATUSES


def create_suggestion(db: Session, **fields: Any) -> ExperimentSuggestion:
    """Создать предложение эксперимента."""
    suggestion = ExperimentSuggestion(**fields)
    db.add(suggestion)
    db.commit()
    db.refresh(suggestion)
    return suggestion


def get_by_id(db: Session, suggestion_id: int) -> ExperimentSuggestion | None:
    """Предложение по id (или None)."""
    return db.get(ExperimentSuggestion, suggestion_id)


def get_by_idempotency_key(db: Session, idempotency_key: str) -> ExperimentSuggestion | None:
    """Найти предложение по ключу идемпотентности (защита от дублей)."""
    return db.scalars(
        select(ExperimentSuggestion).where(ExperimentSuggestion.idempotency_key == idempotency_key)
    ).first()


def list_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    status: str | None = None,
    suggestion_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ExperimentSuggestion]:
    """Предложения проекта (свежие первыми) с фильтрами."""
    stmt = select(ExperimentSuggestion).where(ExperimentSuggestion.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(ExperimentSuggestion.platform_key == platform_key)
    if status is not None:
        stmt = stmt.where(ExperimentSuggestion.status == status)
    if suggestion_type is not None:
        stmt = stmt.where(ExperimentSuggestion.suggestion_type == suggestion_type)
    stmt = stmt.order_by(ExperimentSuggestion.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_for_account(
    db: Session, account_id: int, limit: int = 100, offset: int = 0
) -> list[ExperimentSuggestion]:
    """Предложения аккаунта (свежие первыми)."""
    stmt = (
        select(ExperimentSuggestion)
        .where(ExperimentSuggestion.account_id == account_id)
        .order_by(ExperimentSuggestion.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_active_for_project(db: Session, project_id: int) -> list[ExperimentSuggestion]:
    """Активные предложения проекта (proposed/accepted)."""
    stmt = (
        select(ExperimentSuggestion)
        .where(
            ExperimentSuggestion.project_id == project_id,
            ExperimentSuggestion.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(ExperimentSuggestion.id.desc())
    )
    return list(db.scalars(stmt).all())


def count_active_for_project(db: Session, project_id: int) -> int:
    """Число активных предложений проекта."""
    stmt = select(func.count(ExperimentSuggestion.id)).where(
        ExperimentSuggestion.project_id == project_id,
        ExperimentSuggestion.status.in_(_ACTIVE_STATUSES),
    )
    return int(db.execute(stmt).scalar_one())


def find_recent_similar(
    db: Session,
    project_id: int,
    platform_key: str | None,
    topic: str,
    since: datetime | None = None,  # noqa: ARG001 — сравнение окна делает сервис (tz-safe)
) -> ExperimentSuggestion | None:
    """Найти последнее предложение той же темы/площадки (для cooldown-дедупа).

    Сравнение с окном cooldown выполняет сервисный слой в Python (кросс-СУБД: created_at в
    SQLite наивный, в PostgreSQL — timezone-aware), поэтому здесь возвращаем самое свежее
    совпадение без SQL-фильтра по времени.
    """
    # Точное совпадение темы (SQLite ``lower()`` не понижает кириллицу, поэтому
    # func.lower ненадёжен; рекомендации детерминированы — точного match достаточно).
    normalized = (topic or "").strip()
    stmt = (
        select(ExperimentSuggestion)
        .where(
            ExperimentSuggestion.project_id == project_id,
            ExperimentSuggestion.topic == normalized,
        )
        .order_by(ExperimentSuggestion.id.desc())
    )
    if platform_key is not None:
        stmt = stmt.where(ExperimentSuggestion.platform_key == platform_key)
    else:
        stmt = stmt.where(ExperimentSuggestion.platform_key.is_(None))
    return db.scalars(stmt).first()


def update_suggestion(
    db: Session, suggestion: ExperimentSuggestion, **fields: Any
) -> ExperimentSuggestion:
    """Обновить поля предложения."""
    for field, value in fields.items():
        setattr(suggestion, field, value)
    db.commit()
    db.refresh(suggestion)
    return suggestion


def mark_accepted(
    db: Session, suggestion: ExperimentSuggestion, user_id: int | None, acted_at: datetime
) -> ExperimentSuggestion:
    """Отметить предложение принятым."""
    return update_suggestion(
        db, suggestion, status="accepted", accepted_by_user_id=user_id, acted_at=acted_at
    )


def mark_rejected(
    db: Session,
    suggestion: ExperimentSuggestion,
    user_id: int | None,
    acted_at: datetime,
    reason: str | None = None,
) -> ExperimentSuggestion:
    """Отметить предложение отклонённым."""
    fields: dict[str, Any] = {
        "status": "rejected",
        "rejected_by_user_id": user_id,
        "acted_at": acted_at,
    }
    if reason:
        fields["error_message"] = reason[:2000]
    return update_suggestion(db, suggestion, **fields)


def mark_dismissed(
    db: Session, suggestion: ExperimentSuggestion, user_id: int | None, acted_at: datetime
) -> ExperimentSuggestion:
    """Отметить предложение скрытым."""
    return update_suggestion(
        db, suggestion, status="dismissed", dismissed_by_user_id=user_id, acted_at=acted_at
    )


def mark_experiment_created(
    db: Session, suggestion: ExperimentSuggestion, experiment_id: int, acted_at: datetime
) -> ExperimentSuggestion:
    """Отметить, что из предложения создан эксперимент."""
    return update_suggestion(
        db,
        suggestion,
        status="experiment_created",
        experiment_id=experiment_id,
        acted_at=acted_at,
    )


def mark_failed(
    db: Session, suggestion: ExperimentSuggestion, message: str
) -> ExperimentSuggestion:
    """Отметить предложение как failed (без секретов)."""
    return update_suggestion(db, suggestion, status="failed", error_message=message[:2000])


def mark_expired(db: Session, suggestion: ExperimentSuggestion) -> ExperimentSuggestion:
    """Отметить предложение просроченным."""
    return update_suggestion(db, suggestion, status="expired")


def cleanup_expired(db: Session, project_id: int, now: datetime) -> int:
    """Пометить просроченные (expires_at < now) активные предложения проекта expired."""
    stmt = select(ExperimentSuggestion).where(
        ExperimentSuggestion.project_id == project_id,
        ExperimentSuggestion.status == "proposed",
        ExperimentSuggestion.expires_at.is_not(None),
        ExperimentSuggestion.expires_at < now,
    )
    expired = list(db.scalars(stmt).all())
    for suggestion in expired:
        suggestion.status = "expired"
    if expired:
        db.commit()
    return len(expired)
