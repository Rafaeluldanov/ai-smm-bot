"""Репозиторий прогонов импорта метрик (metric_import_runs).

``import_metadata`` секретов не содержит (обеспечивает сервисный слой). Все выборки
фильтруют по ``project_id``/``account_id`` (tenant-изоляция на уровне сервиса/API).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.metric_import_run import MetricImportRun


def create_run(db: Session, **fields: Any) -> MetricImportRun:
    """Создать прогон импорта метрик."""
    run = MetricImportRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_by_id(db: Session, run_id: int) -> MetricImportRun | None:
    """Вернуть прогон по id (или None)."""
    return db.get(MetricImportRun, run_id)


def get_by_idempotency_key(db: Session, idempotency_key: str) -> MetricImportRun | None:
    """Найти прогон по ключу идемпотентности (защита от дублей)."""
    return db.scalars(
        select(MetricImportRun).where(MetricImportRun.idempotency_key == idempotency_key)
    ).first()


def update_run(db: Session, run: MetricImportRun, **fields: Any) -> MetricImportRun:
    """Обновить поля прогона (updated_at обновляет TimestampMixin)."""
    for field, value in fields.items():
        setattr(run, field, value)
    db.commit()
    db.refresh(run)
    return run


def list_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[MetricImportRun]:
    """Прогоны проекта (свежие первыми)."""
    stmt = (
        select(MetricImportRun)
        .where(MetricImportRun.project_id == project_id)
        .order_by(MetricImportRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_for_account(
    db: Session, account_id: int, limit: int = 100, offset: int = 0
) -> list[MetricImportRun]:
    """Прогоны аккаунта (свежие первыми)."""
    stmt = (
        select(MetricImportRun)
        .where(MetricImportRun.account_id == account_id)
        .order_by(MetricImportRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def mark_imported(
    db: Session,
    run: MetricImportRun,
    *,
    status: str = "imported",
    publications_scanned: int = 0,
    metrics_imported: int = 0,
    snapshots_created: int = 0,
    learning_events_created: int = 0,
    units_charged: int = 0,
    finished_at: Any | None = None,
    import_metadata: dict[str, Any] | None = None,
) -> MetricImportRun:
    """Отметить прогон импортированным (успех/частичный успех) со счётчиками."""
    fields: dict[str, Any] = {
        "status": status,
        "publications_scanned": publications_scanned,
        "metrics_imported": metrics_imported,
        "snapshots_created": snapshots_created,
        "learning_events_created": learning_events_created,
        "units_charged": units_charged,
        "error_message": None,
    }
    if finished_at is not None:
        fields["finished_at"] = finished_at
    if import_metadata is not None:
        fields["import_metadata"] = import_metadata
    return update_run(db, run, **fields)


def mark_failed(
    db: Session, run: MetricImportRun, message: str, finished_at: Any | None = None
) -> MetricImportRun:
    """Отметить прогон как failed с сообщением (без секретов)."""
    fields: dict[str, Any] = {"status": "failed", "error_message": message[:2000]}
    if finished_at is not None:
        fields["finished_at"] = finished_at
    return update_run(db, run, **fields)


def mark_skipped(
    db: Session,
    run: MetricImportRun,
    *,
    status: str = "skipped",
    message: str = "",
    finished_at: Any | None = None,
) -> MetricImportRun:
    """Отметить прогон пропущенным (skipped / no_credentials / live_disabled)."""
    fields: dict[str, Any] = {"status": status, "error_message": message[:2000] or None}
    if finished_at is not None:
        fields["finished_at"] = finished_at
    return update_run(db, run, **fields)
