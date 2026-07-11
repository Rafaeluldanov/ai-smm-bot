"""Репозиторий прогонов расписаний (schedule_runs).

``run_metadata`` секретов не содержит (обеспечивает сервисный слой).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.schedule_run import ScheduleRun


def get_by_id(db: Session, run_id: int) -> ScheduleRun | None:
    """Вернуть прогон по id (или None)."""
    return db.get(ScheduleRun, run_id)


def get_by_idempotency_key(db: Session, key: str) -> ScheduleRun | None:
    """Найти прогон по ключу идемпотентности (защита от дублей)."""
    return db.scalars(select(ScheduleRun).where(ScheduleRun.idempotency_key == key)).first()


def create_run(db: Session, **fields: Any) -> ScheduleRun:
    """Создать прогон расписания."""
    run = ScheduleRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run(db: Session, run: ScheduleRun, **fields: Any) -> ScheduleRun:
    """Обновить поля прогона (updated_at обновляет TimestampMixin)."""
    for field, value in fields.items():
        setattr(run, field, value)
    db.commit()
    db.refresh(run)
    return run


def list_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[ScheduleRun]:
    """Прогоны проекта (свежие первыми)."""
    stmt = (
        select(ScheduleRun)
        .where(ScheduleRun.project_id == project_id)
        .order_by(ScheduleRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_for_account(
    db: Session, account_id: int, limit: int = 100, offset: int = 0
) -> list[ScheduleRun]:
    """Прогоны аккаунта (свежие первыми)."""
    stmt = (
        select(ScheduleRun)
        .where(ScheduleRun.account_id == account_id)
        .order_by(ScheduleRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_for_platform(
    db: Session, project_id: int, platform_key: str, limit: int = 100, offset: int = 0
) -> list[ScheduleRun]:
    """Прогоны проекта по платформе (свежие первыми)."""
    stmt = (
        select(ScheduleRun)
        .where(
            ScheduleRun.project_id == project_id,
            ScheduleRun.platform_key == platform_key,
        )
        .order_by(ScheduleRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_due_like(
    db: Session, project_id: int, run_date: str, platform_key: str | None = None
) -> list[ScheduleRun]:
    """Прогоны проекта за дату (для фильтра/истории)."""
    stmt = select(ScheduleRun).where(
        ScheduleRun.project_id == project_id, ScheduleRun.run_date == run_date
    )
    if platform_key:
        stmt = stmt.where(ScheduleRun.platform_key == platform_key)
    return list(db.scalars(stmt.order_by(ScheduleRun.id.desc())).all())


def mark_failed(db: Session, run: ScheduleRun, message: str) -> ScheduleRun:
    """Отметить прогон как failed с сообщением (без секретов)."""
    return update_run(db, run, status="failed", error_message=message[:2000])


def mark_skipped(db: Session, run: ScheduleRun, message: str = "") -> ScheduleRun:
    """Отметить прогон пропущенным."""
    return update_run(db, run, status="skipped", error_message=message[:2000] or None)


def mark_draft_created(
    db: Session, run: ScheduleRun, post_id: int, publication_id: int | None, units_charged: int
) -> ScheduleRun:
    """Отметить прогон как создавший draft (с постом/публикацией/units)."""
    return update_run(
        db,
        run,
        status="draft_created",
        post_id=post_id,
        publication_id=publication_id,
        units_charged=units_charged,
        error_message=None,
    )
