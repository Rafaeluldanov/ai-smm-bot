"""Репозиторий решений о медиа слота расписания (schedule_media_decisions).

``alternatives``/``source_signals``/``decision_metadata`` секретов и внутренних путей к
файлам не содержат (обеспечивает сервисный слой). Все выборки фильтруют по
``project_id``/``account_id`` (изоляция — на API/сервисном слое).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule_media_decision import ScheduleMediaDecision


def create_decision(db: Session, **fields: Any) -> ScheduleMediaDecision:
    """Создать решение о медиа слота."""
    decision = ScheduleMediaDecision(**fields)
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def get_by_id(db: Session, decision_id: int) -> ScheduleMediaDecision | None:
    """Решение по id (или None)."""
    return db.get(ScheduleMediaDecision, decision_id)


def get_by_idempotency_key(db: Session, idempotency_key: str) -> ScheduleMediaDecision | None:
    """Найти решение по ключу идемпотентности (защита от дублей)."""
    return db.scalars(
        select(ScheduleMediaDecision).where(
            ScheduleMediaDecision.idempotency_key == idempotency_key
        )
    ).first()


def list_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    status: str | None = None,
    strategy: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ScheduleMediaDecision]:
    """Решения проекта (свежие первыми) с фильтрами платформа/статус/стратегия."""
    stmt = select(ScheduleMediaDecision).where(ScheduleMediaDecision.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(ScheduleMediaDecision.platform_key == platform_key)
    if status is not None:
        stmt = stmt.where(ScheduleMediaDecision.status == status)
    if strategy is not None:
        stmt = stmt.where(ScheduleMediaDecision.selected_strategy == strategy)
    stmt = stmt.order_by(ScheduleMediaDecision.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_for_schedule_run(db: Session, schedule_run_id: int) -> list[ScheduleMediaDecision]:
    """Решения, привязанные к прогону расписания."""
    stmt = (
        select(ScheduleMediaDecision)
        .where(ScheduleMediaDecision.schedule_run_id == schedule_run_id)
        .order_by(ScheduleMediaDecision.id.desc())
    )
    return list(db.scalars(stmt).all())


def list_for_platform(
    db: Session, project_id: int, platform_key: str, limit: int = 100
) -> list[ScheduleMediaDecision]:
    """Решения проекта по конкретной платформе (свежие первыми)."""
    stmt = (
        select(ScheduleMediaDecision)
        .where(
            ScheduleMediaDecision.project_id == project_id,
            ScheduleMediaDecision.platform_key == platform_key,
        )
        .order_by(ScheduleMediaDecision.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_decision(
    db: Session, decision: ScheduleMediaDecision, **fields: Any
) -> ScheduleMediaDecision:
    """Обновить поля решения."""
    for field, value in fields.items():
        setattr(decision, field, value)
    db.commit()
    db.refresh(decision)
    return decision


def mark_selected(db: Session, decision: ScheduleMediaDecision) -> ScheduleMediaDecision:
    """Отметить решение выбранным (медиа выбрано, драфт ещё не создан)."""
    return update_decision(db, decision, status="selected")


def mark_applied_to_draft(
    db: Session,
    decision: ScheduleMediaDecision,
    schedule_run_id: int | None,
    post_id: int | None,
) -> ScheduleMediaDecision:
    """Отметить, что по решению создан draft (привязать run/post в metadata)."""
    meta = dict(decision.decision_metadata or {})
    if post_id is not None:
        meta["post_id"] = post_id
    return update_decision(
        db,
        decision,
        status="applied_to_draft",
        schedule_run_id=schedule_run_id
        if schedule_run_id is not None
        else decision.schedule_run_id,
        decision_metadata=meta,
    )


def mark_skipped(
    db: Session, decision: ScheduleMediaDecision, reason: str | None = None
) -> ScheduleMediaDecision:
    """Отметить решение пропущенным (например, дубль/ниже порога)."""
    fields: dict[str, Any] = {"status": "skipped"}
    if reason:
        fields["error_message"] = reason[:2000]
    return update_decision(db, decision, **fields)


def mark_failed(
    db: Session, decision: ScheduleMediaDecision, message: str
) -> ScheduleMediaDecision:
    """Отметить решение как failed (без секретов/путей)."""
    return update_decision(db, decision, status="failed", error_message=message[:2000])


def find_recent_media_usage(
    db: Session, project_id: int, asset_id: int, limit: int = 100
) -> ScheduleMediaDecision | None:
    """Последнее применённое решение проекта, использовавшее данный media asset.

    Проверка вхождения id в JSON-список делается в Python (кросс-СУБД: SQLite/PostgreSQL
    по-разному индексируют JSON).
    """
    stmt = (
        select(ScheduleMediaDecision)
        .where(
            ScheduleMediaDecision.project_id == project_id,
            ScheduleMediaDecision.status.in_(("applied_to_draft", "selected")),
        )
        .order_by(ScheduleMediaDecision.id.desc())
        .limit(limit)
    )
    for decision in db.scalars(stmt).all():
        if asset_id in (decision.selected_media_asset_ids or []):
            return decision
    return None


def count_recent_media_usage(db: Session, project_id: int, asset_id: int, limit: int = 200) -> int:
    """Сколько недавних применённых решений использовали данный media asset (для «усталости»)."""
    stmt = (
        select(ScheduleMediaDecision)
        .where(
            ScheduleMediaDecision.project_id == project_id,
            ScheduleMediaDecision.status.in_(("applied_to_draft", "selected")),
        )
        .order_by(ScheduleMediaDecision.id.desc())
        .limit(limit)
    )
    return sum(
        1
        for decision in db.scalars(stmt).all()
        if asset_id in (decision.selected_media_asset_ids or [])
    )
