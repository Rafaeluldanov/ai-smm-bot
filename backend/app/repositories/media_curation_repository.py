"""Репозиторий задач курирования медиатеки (media_curation_tasks) + видимость медиа.

``suggested_*``/``task_metadata`` секретов и внутренних путей к файлам не содержат
(обеспечивает сервисный слой). Все выборки фильтруют по ``project_id`` (изоляция — на
API/сервисном слое). Файлы НЕ удаляются; меняется только видимость/теги (после подтверждения).
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.media_curation_task import MediaCurationTask

_ACTIVE_STATUSES = ("proposed", "accepted")


def create_task(db: Session, **fields: Any) -> MediaCurationTask:
    """Создать задачу курирования."""
    task = MediaCurationTask(**fields)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task_by_id(db: Session, task_id: int) -> MediaCurationTask | None:
    """Задача по id (или None)."""
    return db.get(MediaCurationTask, task_id)


def get_by_idempotency_key(db: Session, idempotency_key: str) -> MediaCurationTask | None:
    """Найти задачу по ключу идемпотентности (защита от дублей)."""
    return db.scalars(
        select(MediaCurationTask).where(MediaCurationTask.idempotency_key == idempotency_key)
    ).first()


def list_tasks_for_project(
    db: Session,
    project_id: int,
    status: str | None = None,
    task_type: str | None = None,
    media_asset_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MediaCurationTask]:
    """Задачи проекта (свежие первыми) с фильтрами статус/тип/медиа."""
    stmt = select(MediaCurationTask).where(MediaCurationTask.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaCurationTask.status == status)
    if task_type is not None:
        stmt = stmt.where(MediaCurationTask.task_type == task_type)
    if media_asset_id is not None:
        stmt = stmt.where(MediaCurationTask.media_asset_id == media_asset_id)
    stmt = stmt.order_by(MediaCurationTask.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_active_tasks_for_project(
    db: Session, project_id: int, limit: int = 500
) -> list[MediaCurationTask]:
    """Активные задачи проекта (proposed/accepted)."""
    stmt = (
        select(MediaCurationTask)
        .where(
            MediaCurationTask.project_id == project_id,
            MediaCurationTask.status.in_(_ACTIVE_STATUSES),
        )
        .order_by(MediaCurationTask.confidence_score.desc(), MediaCurationTask.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_tasks_for_media_asset(
    db: Session, project_id: int, media_asset_id: int
) -> list[MediaCurationTask]:
    """Задачи проекта, связанные с данным медиа."""
    stmt = (
        select(MediaCurationTask)
        .where(
            MediaCurationTask.project_id == project_id,
            MediaCurationTask.media_asset_id == media_asset_id,
        )
        .order_by(MediaCurationTask.id.desc())
    )
    return list(db.scalars(stmt).all())


def update_task(db: Session, task: MediaCurationTask, **fields: Any) -> MediaCurationTask:
    """Обновить поля задачи."""
    for field, value in fields.items():
        setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


def mark_accepted(
    db: Session, task: MediaCurationTask, user_id: int | None = None
) -> MediaCurationTask:
    """Отметить задачу принятой (клиент согласился)."""
    return update_task(db, task, status="accepted")


def mark_rejected(
    db: Session, task: MediaCurationTask, reason: str | None = None, user_id: int | None = None
) -> MediaCurationTask:
    """Отметить задачу отклонённой (без изменений медиа)."""
    fields: dict[str, Any] = {
        "status": "rejected",
        "rejected_by_user_id": user_id,
        "rejected_at": datetime.now(UTC),
    }
    if reason:
        fields["reason"] = reason[:2000]
    return update_task(db, task, **fields)


def mark_applied(
    db: Session, task: MediaCurationTask, user_id: int | None = None
) -> MediaCurationTask:
    """Отметить задачу применённой (теги/видимость обновлены после подтверждения)."""
    return update_task(
        db, task, status="applied", applied_by_user_id=user_id, applied_at=datetime.now(UTC)
    )


def mark_ignored(
    db: Session, task: MediaCurationTask, user_id: int | None = None
) -> MediaCurationTask:
    """Отметить задачу проигнорированной."""
    return update_task(
        db, task, status="ignored", ignored_by_user_id=user_id, ignored_at=datetime.now(UTC)
    )


def mark_restored(
    db: Session, task: MediaCurationTask, user_id: int | None = None
) -> MediaCurationTask:
    """Отметить задачу как восстановленную (медиа возвращено в подбор)."""
    return update_task(db, task, status="restored")


def expire_old_tasks(db: Session, project_id: int, now: datetime | None = None) -> int:
    """Просрочить proposed-задачи с истёкшим expires_at; вернуть число."""
    ref = now or datetime.now(UTC)
    stmt = select(MediaCurationTask).where(
        MediaCurationTask.project_id == project_id,
        MediaCurationTask.status == "proposed",
        MediaCurationTask.expires_at.is_not(None),
        MediaCurationTask.expires_at < ref,
    )
    count = 0
    for task in db.scalars(stmt).all():
        task.status = "expired"
        count += 1
    if count:
        db.commit()
    return count


def get_dashboard_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Лёгкая агрегированная сводка (счётчики по типу/статусу)."""
    tasks = list_tasks_for_project(db, project_id, limit=2000)
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for task in tasks:
        by_type[task.task_type] = by_type.get(task.task_type, 0) + 1
        by_status[task.status] = by_status.get(task.status, 0) + 1
    return {"total_tasks": len(tasks), "by_type": by_type, "by_status": by_status}


# --- Видимость медиа (без удаления файлов) --- #


def set_media_visibility(
    db: Session, media_asset_id: int, visibility: str, notes: dict[str, Any] | None = None
) -> MediaAsset | None:
    """Задать видимость медиа для авто-подбора (файл НЕ трогаем)."""
    asset = db.get(MediaAsset, media_asset_id)
    if asset is None:
        return None
    asset.selection_visibility = visibility
    if notes is not None:
        merged = dict(asset.curation_notes or {})
        merged.update(notes)
        asset.curation_notes = merged
    db.commit()
    db.refresh(asset)
    return asset


def restore_media_visibility(db: Session, media_asset_id: int) -> MediaAsset | None:
    """Вернуть медиа в подбор (selectable) — файл НЕ трогаем."""
    asset = db.get(MediaAsset, media_asset_id)
    if asset is None:
        return None
    asset.selection_visibility = "selectable"
    asset.curation_status = "reviewed"
    db.commit()
    db.refresh(asset)
    return asset


def list_selectable_media_assets(db: Session, project_id: int) -> list[MediaAsset]:
    """Медиа проекта, доступные авто-подбору (selection_visibility == selectable)."""
    stmt = select(MediaAsset).where(
        MediaAsset.project_id == project_id,
        MediaAsset.selection_visibility == "selectable",
    )
    return list(db.scalars(stmt).all())


def count_hidden_media(db: Session, project_id: int) -> int:
    """Сколько медиа проекта скрыто из подбора (не selectable)."""
    stmt = select(MediaAsset).where(
        MediaAsset.project_id == project_id,
        MediaAsset.selection_visibility != "selectable",
    )
    return len(list(db.scalars(stmt).all()))
