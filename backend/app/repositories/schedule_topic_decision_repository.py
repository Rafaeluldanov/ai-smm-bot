"""Репозиторий решений о теме слота расписания (schedule_topic_decisions).

``alternatives``/``source_signals``/``decision_metadata`` секретов не содержат (обеспечивает
сервисный слой). Все выборки фильтруют по ``project_id``/``account_id`` (изоляция — на
API/сервисном слое).
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.schedule_topic_decision import ScheduleTopicDecision


def create_decision(db: Session, **fields: Any) -> ScheduleTopicDecision:
    """Создать решение о теме слота."""
    decision = ScheduleTopicDecision(**fields)
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def get_by_id(db: Session, decision_id: int) -> ScheduleTopicDecision | None:
    """Решение по id (или None)."""
    return db.get(ScheduleTopicDecision, decision_id)


def get_by_idempotency_key(db: Session, idempotency_key: str) -> ScheduleTopicDecision | None:
    """Найти решение по ключу идемпотентности (защита от дублей)."""
    return db.scalars(
        select(ScheduleTopicDecision).where(
            ScheduleTopicDecision.idempotency_key == idempotency_key
        )
    ).first()


def list_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    status: str | None = None,
    decision_source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ScheduleTopicDecision]:
    """Решения проекта (свежие первыми) с фильтрами платформа/статус/источник."""
    stmt = select(ScheduleTopicDecision).where(ScheduleTopicDecision.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(ScheduleTopicDecision.platform_key == platform_key)
    if status is not None:
        stmt = stmt.where(ScheduleTopicDecision.status == status)
    if decision_source is not None:
        stmt = stmt.where(ScheduleTopicDecision.decision_source == decision_source)
    stmt = stmt.order_by(ScheduleTopicDecision.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_for_schedule_run(db: Session, schedule_run_id: int) -> list[ScheduleTopicDecision]:
    """Решения, привязанные к прогону расписания."""
    stmt = (
        select(ScheduleTopicDecision)
        .where(ScheduleTopicDecision.schedule_run_id == schedule_run_id)
        .order_by(ScheduleTopicDecision.id.desc())
    )
    return list(db.scalars(stmt).all())


def list_for_platform(
    db: Session, project_id: int, platform_key: str, limit: int = 100
) -> list[ScheduleTopicDecision]:
    """Решения проекта по конкретной платформе (свежие первыми)."""
    stmt = (
        select(ScheduleTopicDecision)
        .where(
            ScheduleTopicDecision.project_id == project_id,
            ScheduleTopicDecision.platform_key == platform_key,
        )
        .order_by(ScheduleTopicDecision.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_decision(
    db: Session, decision: ScheduleTopicDecision, **fields: Any
) -> ScheduleTopicDecision:
    """Обновить поля решения."""
    for field, value in fields.items():
        setattr(decision, field, value)
    db.commit()
    db.refresh(decision)
    return decision


def mark_selected(db: Session, decision: ScheduleTopicDecision) -> ScheduleTopicDecision:
    """Отметить решение выбранным (тема выбрана, драфт ещё не создан)."""
    return update_decision(db, decision, status="selected")


def mark_draft_created(
    db: Session,
    decision: ScheduleTopicDecision,
    schedule_run_id: int | None,
    post_id: int | None,
) -> ScheduleTopicDecision:
    """Отметить, что по решению создан draft (привязать run/post в metadata)."""
    meta = dict(decision.decision_metadata or {})
    if post_id is not None:
        meta["post_id"] = post_id
    return update_decision(
        db,
        decision,
        status="draft_created",
        schedule_run_id=schedule_run_id
        if schedule_run_id is not None
        else decision.schedule_run_id,
        decision_metadata=meta,
    )


def mark_skipped(
    db: Session, decision: ScheduleTopicDecision, reason: str | None = None
) -> ScheduleTopicDecision:
    """Отметить решение пропущенным (например, дубль/ниже порога)."""
    fields: dict[str, Any] = {"status": "skipped"}
    if reason:
        fields["error_message"] = reason[:2000]
    return update_decision(db, decision, **fields)


def mark_failed(
    db: Session, decision: ScheduleTopicDecision, message: str
) -> ScheduleTopicDecision:
    """Отметить решение как failed (без секретов)."""
    return update_decision(db, decision, status="failed", error_message=message[:2000])


def find_recent_similar_topic(
    db: Session, project_id: int, platform_key: str | None, topic: str
) -> ScheduleTopicDecision | None:
    """Последнее решение той же темы/площадки (для дедупа; окно считает сервис, tz-safe).

    Точное совпадение темы: SQLite ``lower()`` не понижает кириллицу, поэтому ``func.lower``
    ненадёжен; решения детерминированы — точного match достаточно.
    """
    normalized = (topic or "").strip()
    stmt = (
        select(ScheduleTopicDecision)
        .where(
            ScheduleTopicDecision.project_id == project_id,
            ScheduleTopicDecision.selected_topic == normalized,
        )
        .order_by(ScheduleTopicDecision.id.desc())
    )
    if platform_key is not None:
        stmt = stmt.where(ScheduleTopicDecision.platform_key == platform_key)
    else:
        stmt = stmt.where(ScheduleTopicDecision.platform_key.is_(None))
    return db.scalars(stmt).first()


def count_recent_topic_usage(
    db: Session, project_id: int, topic: str, statuses: tuple[str, ...] = ("draft_created",)
) -> int:
    """Сколько раз тема уже выбрана (для «усталости»)."""
    normalized = (topic or "").strip()
    stmt = select(func.count(ScheduleTopicDecision.id)).where(
        ScheduleTopicDecision.project_id == project_id,
        ScheduleTopicDecision.selected_topic == normalized,
        ScheduleTopicDecision.status.in_(statuses),
    )
    return int(db.execute(stmt).scalar_one())
