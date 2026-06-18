"""Репозиторий автономных прогонов и их шагов (Этап 10)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autonomous_run import AutonomousRun
from app.models.autonomous_run_step import AutonomousRunStep
from app.schemas.autonomous import (
    AutonomousRunCreate,
    AutonomousRunStepCreate,
    AutonomousRunStepUpdate,
    AutonomousRunUpdate,
)


def get_run_by_id(db: Session, run_id: int) -> AutonomousRun | None:
    """Вернуть прогон по id или None."""
    return db.get(AutonomousRun, run_id)


def list_runs(
    db: Session,
    project_id: int | None = None,
    status: str | None = None,
    mode: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AutonomousRun]:
    """Вернуть прогоны с фильтрами и пагинацией (новые — выше)."""
    stmt = select(AutonomousRun).order_by(AutonomousRun.id.desc())
    if project_id is not None:
        stmt = stmt.where(AutonomousRun.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AutonomousRun.status == status)
    if mode is not None:
        stmt = stmt.where(AutonomousRun.mode == mode)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def create_run(db: Session, data: AutonomousRunCreate) -> AutonomousRun:
    """Создать прогон."""
    run = AutonomousRun(**data.model_dump())
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_run(db: Session, run: AutonomousRun, data: AutonomousRunUpdate) -> AutonomousRun:
    """Частично обновить прогон (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(run, field, value)
    db.commit()
    db.refresh(run)
    return run


def create_step(db: Session, data: AutonomousRunStepCreate) -> AutonomousRunStep:
    """Создать шаг прогона."""
    step = AutonomousRunStep(**data.model_dump())
    db.add(step)
    db.commit()
    db.refresh(step)
    return step


def update_step(
    db: Session, step: AutonomousRunStep, data: AutonomousRunStepUpdate
) -> AutonomousRunStep:
    """Частично обновить шаг прогона (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(step, field, value)
    db.commit()
    db.refresh(step)
    return step


def list_steps(db: Session, run_id: int) -> list[AutonomousRunStep]:
    """Вернуть шаги прогона в хронологическом порядке."""
    stmt = (
        select(AutonomousRunStep)
        .where(AutonomousRunStep.run_id == run_id)
        .order_by(AutonomousRunStep.id)
    )
    return list(db.scalars(stmt).all())


def get_latest_run_for_project(db: Session, project_id: int) -> AutonomousRun | None:
    """Вернуть последний прогон проекта или None."""
    stmt = (
        select(AutonomousRun)
        .where(AutonomousRun.project_id == project_id)
        .order_by(AutonomousRun.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()
