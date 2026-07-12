"""Репозиторий collaborative review курирования медиатеки (v0.4.9).

Ведёт статус согласования (``review_status``), ответственных, сроки, комментарии и историю
решений (timeline). Комментарии и public-dict секретов/внутренних путей не содержат
(санитизация — на сервисном слое). Все выборки фильтруют по ``project_id``; изоляция
обеспечивается API/сервисом. Файлы НЕ удаляются; комментарии физически НЕ удаляются в MVP.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.media_curation_comment import MediaCurationComment
from app.models.media_curation_task import (
    MEDIA_CURATION_PRIORITY_ORDER,
    MediaCurationTask,
)

# Активные (незавершённые) статусы согласования — для «моих задач»/overdue.
_ACTIVE_REVIEW_STATUSES = (
    "proposed",
    "assigned",
    "in_review",
    "changes_requested",
    "approved",
)
_TERMINAL_REVIEW_STATUSES = ("applied", "rejected", "ignored", "expired", "failed")


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# --- История решений (events в review_metadata) --- #


def append_review_event(
    task: MediaCurationTask,
    kind: str,
    user_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Добавить событие истории в ``review_metadata['events']`` (без секретов/путей).

    Реассайним словарь целиком, чтобы SQLAlchemy зафиксировал изменение JSON-поля.
    """
    meta = dict(task.review_metadata or {})
    events = list(meta.get("events") or [])
    event: dict[str, Any] = {
        "kind": kind,
        "at": _iso(_now()),
        "user_id": user_id,
    }
    if extra:
        event.update(extra)
    events.append(event)
    meta["events"] = events[-200:]  # мягкий предел длины истории
    task.review_metadata = meta


# --- Комментарии --- #


def create_comment(
    db: Session,
    *,
    project_id: int,
    task_id: int,
    account_id: int | None = None,
    user_id: int | None = None,
    comment_text: str = "",
    comment_type: str = "comment",
    comment_metadata: dict[str, Any] | None = None,
) -> MediaCurationComment:
    """Создать комментарий к задаче (текст должен быть уже санитизирован сервисом)."""
    comment = MediaCurationComment(
        account_id=account_id,
        project_id=project_id,
        task_id=task_id,
        user_id=user_id,
        comment_text=comment_text[:4000],
        comment_type=comment_type,
        comment_metadata=comment_metadata or {},
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def list_comments_for_task(
    db: Session, task_id: int, limit: int = 200, offset: int = 0
) -> list[MediaCurationComment]:
    """Комментарии задачи (старые первыми — как хронология обсуждения)."""
    stmt = (
        select(MediaCurationComment)
        .where(MediaCurationComment.task_id == task_id)
        .order_by(MediaCurationComment.id.asc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def get_comment_by_id(db: Session, comment_id: int) -> MediaCurationComment | None:
    """Комментарий по id (или None)."""
    return db.get(MediaCurationComment, comment_id)


def count_comments_for_task(db: Session, task_id: int) -> int:
    """Число комментариев задачи (для лимита на задачу)."""
    stmt = (
        select(func.count())
        .select_from(MediaCurationComment)
        .where(MediaCurationComment.task_id == task_id)
    )
    return int(db.scalar(stmt) or 0)


# --- Задачи: фильтры и списки --- #


def list_review_tasks(
    db: Session,
    project_id: int,
    review_status: str | None = None,
    priority: str | None = None,
    assignee_user_id: int | None = None,
    task_type: str | None = None,
    overdue: bool = False,
    overdue_ref: datetime | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MediaCurationTask]:
    """Задачи проекта для доски ревью (по фильтрам). Свежие/важные первыми."""
    stmt = select(MediaCurationTask).where(MediaCurationTask.project_id == project_id)
    if review_status is not None:
        stmt = stmt.where(MediaCurationTask.review_status == review_status)
    if priority is not None:
        stmt = stmt.where(MediaCurationTask.priority == priority)
    if assignee_user_id is not None:
        stmt = stmt.where(MediaCurationTask.assignee_user_id == assignee_user_id)
    if task_type is not None:
        stmt = stmt.where(MediaCurationTask.task_type == task_type)
    if overdue:
        ref = overdue_ref or _now()
        stmt = stmt.where(
            MediaCurationTask.due_at.is_not(None),
            MediaCurationTask.due_at < ref,
            MediaCurationTask.review_status.in_(_ACTIVE_REVIEW_STATUSES),
        )
    stmt = stmt.order_by(MediaCurationTask.id.desc()).limit(limit).offset(offset)
    rows = list(db.scalars(stmt).all())
    # Приоритет: важнее — выше (стабильно, вторичный ключ — свежесть).
    rows.sort(
        key=lambda t: (MEDIA_CURATION_PRIORITY_ORDER.get(t.priority, 1), t.id),
        reverse=True,
    )
    return rows


def list_tasks_for_assignee(
    db: Session, project_id: int, assignee_user_id: int, active_only: bool = True, limit: int = 200
) -> list[MediaCurationTask]:
    """Задачи, назначенные пользователю (по умолчанию только активные)."""
    stmt = select(MediaCurationTask).where(
        MediaCurationTask.project_id == project_id,
        MediaCurationTask.assignee_user_id == assignee_user_id,
    )
    if active_only:
        stmt = stmt.where(MediaCurationTask.review_status.in_(_ACTIVE_REVIEW_STATUSES))
    stmt = stmt.order_by(MediaCurationTask.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def list_overdue_tasks(
    db: Session, project_id: int, ref: datetime | None = None, limit: int = 200
) -> list[MediaCurationTask]:
    """Просроченные активные задачи (due_at < now)."""
    reference = ref or _now()
    stmt = (
        select(MediaCurationTask)
        .where(
            MediaCurationTask.project_id == project_id,
            MediaCurationTask.due_at.is_not(None),
            MediaCurationTask.due_at < reference,
            MediaCurationTask.review_status.in_(_ACTIVE_REVIEW_STATUSES),
        )
        .order_by(MediaCurationTask.due_at.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


# --- Переходы статуса согласования --- #


def update_task_review_status(
    db: Session, task: MediaCurationTask, review_status: str, **fields: Any
) -> MediaCurationTask:
    """Задать review_status и произвольные поля; закоммитить."""
    task.review_status = review_status
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()
    db.refresh(task)
    return task


def assign_task(
    db: Session, task: MediaCurationTask, assignee_user_id: int, current_user_id: int | None = None
) -> MediaCurationTask:
    """Назначить ответственного; review_status=assigned (если ещё не в работе)."""
    task.assignee_user_id = assignee_user_id
    if task.review_status in ("proposed", "assigned"):
        task.review_status = "assigned"
    append_review_event(task, "assigned", current_user_id, {"assignee_user_id": assignee_user_id})
    db.commit()
    db.refresh(task)
    return task


def unassign_task(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Снять ответственного; вернуть в proposed, если задача была лишь assigned."""
    task.assignee_user_id = None
    if task.review_status == "assigned":
        task.review_status = "proposed"
    append_review_event(task, "unassigned", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def set_priority(
    db: Session, task: MediaCurationTask, priority: str, current_user_id: int | None = None
) -> MediaCurationTask:
    """Задать приоритет задачи."""
    task.priority = priority
    append_review_event(task, "priority_set", current_user_id, {"priority": priority})
    db.commit()
    db.refresh(task)
    return task


def set_due_at(
    db: Session,
    task: MediaCurationTask,
    due_at: datetime | None,
    current_user_id: int | None = None,
) -> MediaCurationTask:
    """Задать срок задачи (due_at)."""
    task.due_at = due_at
    append_review_event(task, "due_set", current_user_id, {"due_at": _iso(due_at)})
    db.commit()
    db.refresh(task)
    return task


def mark_in_review(
    db: Session, task: MediaCurationTask, reviewer_user_id: int | None = None
) -> MediaCurationTask:
    """Начать проверку: review_status=in_review, зафиксировать reviewer."""
    task.review_status = "in_review"
    if reviewer_user_id is not None:
        task.reviewer_user_id = reviewer_user_id
    append_review_event(task, "started", reviewer_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_changes_requested(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Запросить правки: review_status=changes_requested."""
    task.review_status = "changes_requested"
    task.changes_requested_at = _now()
    append_review_event(task, "changes_requested", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_approved(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Одобрить задачу: review_status=approved, approved_at/reviewed_at."""
    now = _now()
    task.review_status = "approved"
    task.approved_at = now
    if task.reviewed_at is None:
        task.reviewed_at = now
    if current_user_id is not None and task.reviewer_user_id is None:
        task.reviewer_user_id = current_user_id
    append_review_event(task, "approved", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_rejected(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Отклонить задачу: review_status=rejected (без изменений медиа)."""
    now = _now()
    task.review_status = "rejected"
    if task.reviewed_at is None:
        task.reviewed_at = now
    task.rejected_by_user_id = current_user_id
    task.rejected_at = now
    task.status = "rejected"
    append_review_event(task, "rejected", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_applied(
    db: Session,
    task: MediaCurationTask,
    current_user_id: int | None = None,
    before_state: dict[str, Any] | None = None,
    after_state: dict[str, Any] | None = None,
    decision_summary: dict[str, Any] | None = None,
) -> MediaCurationTask:
    """Отметить применённой (после approved): review_status=applied + before/after."""
    now = _now()
    task.review_status = "applied"
    task.status = "applied"
    task.applied_by_user_id = current_user_id
    task.applied_at = now
    if before_state is not None:
        task.before_state = before_state
    if after_state is not None:
        task.after_state = after_state
    if decision_summary is not None:
        task.decision_summary = decision_summary
    append_review_event(task, "applied", current_user_id, {"decision": decision_summary or {}})
    db.commit()
    db.refresh(task)
    return task


def mark_ignored(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Проигнорировать задачу: review_status=ignored (без изменений медиа)."""
    now = _now()
    task.review_status = "ignored"
    task.status = "ignored"
    task.ignored_by_user_id = current_user_id
    task.ignored_at = now
    append_review_event(task, "ignored", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_restored(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Отметить восстановление медиа: review_status=restored."""
    task.review_status = "restored"
    task.status = "restored"
    append_review_event(task, "restored", current_user_id)
    db.commit()
    db.refresh(task)
    return task


def mark_expired(
    db: Session, task: MediaCurationTask, current_user_id: int | None = None
) -> MediaCurationTask:
    """Просрочить задачу ревью: review_status=expired."""
    task.review_status = "expired"
    append_review_event(task, "expired", current_user_id)
    db.commit()
    db.refresh(task)
    return task


# --- Timeline (история решений + комментарии) --- #


def build_review_timeline(db: Session, task: MediaCurationTask) -> list[dict[str, Any]]:
    """Собрать хронологию задачи: системные события + комментарии, отсортированные по времени."""
    events: list[dict[str, Any]] = []
    events.append(
        {
            "kind": "created",
            "at": _iso(task.created_at),
            "user_id": None,
            "review_status": "proposed",
        }
    )
    for ev in (task.review_metadata or {}).get("events") or []:
        events.append(
            {
                "kind": ev.get("kind", "event"),
                "at": ev.get("at"),
                "user_id": ev.get("user_id"),
                **{k: v for k, v in ev.items() if k not in ("kind", "at", "user_id")},
            }
        )
    for comment in list_comments_for_task(db, task.id, limit=500):
        events.append(
            {
                "kind": "comment",
                "at": _iso(comment.created_at),
                "user_id": comment.user_id,
                "comment_id": comment.id,
                "comment_type": comment.comment_type,
                "comment_text": comment.comment_text,
            }
        )
    events.sort(key=lambda e: (e.get("at") or "", e.get("comment_id") or 0))
    return events
