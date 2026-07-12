"""REST API collaborative review курирования медиатеки (v0.4.9).

Все роуты — под tenant-изоляцией (проект/задача). Комментарии/approve/reject/apply бесплатны
(без внешнего AI). Изменения применяются ТОЛЬКО после approved; файлы НЕ удаляются (нет
delete-роута/live-публикаций). Секретов и внутренних путей к файлам в ответах нет.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_media_curation_review_service, get_optional_user
from app.api.security_guards import require_media_curation_task_access, require_project_access
from app.models.user import User
from app.services.media_curation_review_service import (
    MediaCurationReviewError,
    MediaCurationReviewService,
)
from app.services.media_curation_service import MediaCurationError

router = APIRouter(prefix="/media-curation-review", tags=["media-curation-review"])

DbSession = Annotated[Session, Depends(get_db)]
ReviewSvc = Annotated[MediaCurationReviewService, Depends(get_media_curation_review_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except (MediaCurationReviewError, MediaCurationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


def _parse_due(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный формат due_at (ISO 8601)"
        ) from exc


# --- Запросы ---


class CommentRequest(BaseModel):
    """Комментарий к задаче ревью."""

    comment_text: str
    comment_type: str = "comment"


class AssignRequest(BaseModel):
    """Назначение ответственного (+ опционально приоритет/срок)."""

    assignee_user_id: int
    priority: str | None = None
    due_at: str | None = None


class CommentBody(BaseModel):
    """Комментарий при запросе правок/одобрении."""

    comment: str | None = None


class RejectRequest(BaseModel):
    """Отклонение задачи."""

    reason: str | None = None


class ApplyRequest(BaseModel):
    """Применение одобренной задачи."""

    action: str = "mark_reviewed"


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_tasks(
    project_id: int,
    db: DbSession,
    service: ReviewSvc,
    review_status: str | None = None,
    priority: str | None = None,
    assignee_user_id: int | None = None,
    task_type: str | None = None,
    overdue: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список задач ревью проекта (фильтры статус/приоритет/ответственный/тип/overdue)."""
    return _run(
        lambda: service.list_review_tasks(
            db,
            project_id,
            review_status=review_status,
            priority=priority,
            assignee_user_id=assignee_user_id,
            task_type=task_type,
            overdue=overdue,
            limit=limit,
            offset=offset,
        )
    )


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(project_id: int, db: DbSession, service: ReviewSvc, user: OptUser) -> dict[str, Any]:
    """Сводка доски ревью проекта (счётчики, overdue, мои задачи)."""
    return _run(lambda: service.build_review_dashboard(db, project_id, _uid(user)))


# --- Роуты задачи ---


@router.get("/tasks/{task_id}", dependencies=[Depends(require_media_curation_task_access)])
def get_task(task_id: int, db: DbSession, service: ReviewSvc) -> dict[str, Any]:
    """Детали задачи ревью: задача, комментарии, timeline, before/after, safety."""
    return _run(lambda: service.get_task_detail(db, None, task_id))


@router.get("/tasks/{task_id}/comments", dependencies=[Depends(require_media_curation_task_access)])
def list_comments(task_id: int, db: DbSession, service: ReviewSvc) -> list[dict[str, Any]]:
    """Комментарии задачи (хронология)."""
    return _run(lambda: service.list_comments(db, None, task_id))


@router.post(
    "/tasks/{task_id}/comments", dependencies=[Depends(require_media_curation_task_access)]
)
def add_comment(
    task_id: int, payload: CommentRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Добавить комментарий к задаче (санитизация; без секретов/путей)."""
    return _run(
        lambda: service.add_comment(
            db, task_id, payload.comment_text, _uid(user), payload.comment_type
        )
    )


@router.post("/tasks/{task_id}/assign", dependencies=[Depends(require_media_curation_task_access)])
def assign(
    task_id: int, payload: AssignRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Назначить ответственного (+ опционально приоритет/срок)."""
    due = _parse_due(payload.due_at)
    return _run(
        lambda: service.assign_task(
            db,
            task_id,
            payload.assignee_user_id,
            _uid(user),
            priority=payload.priority,
            due_at=due,
        )
    )


@router.post(
    "/tasks/{task_id}/start-review", dependencies=[Depends(require_media_curation_task_access)]
)
def start_review(task_id: int, db: DbSession, service: ReviewSvc, user: OptUser) -> dict[str, Any]:
    """Начать проверку задачи (in_review)."""
    return _run(lambda: service.start_review(db, task_id, _uid(user)))


@router.post(
    "/tasks/{task_id}/request-changes",
    dependencies=[Depends(require_media_curation_task_access)],
)
def request_changes(
    task_id: int, payload: CommentBody, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Запросить правки (changes_requested) + комментарий."""
    return _run(lambda: service.request_changes(db, task_id, payload.comment, _uid(user)))


@router.post("/tasks/{task_id}/approve", dependencies=[Depends(require_media_curation_task_access)])
def approve(
    task_id: int, payload: CommentBody, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Одобрить задачу (approved). Не применяет автоматически (по умолчанию)."""
    return _run(lambda: service.approve_task(db, task_id, payload.comment, _uid(user)))


@router.post("/tasks/{task_id}/reject", dependencies=[Depends(require_media_curation_task_access)])
def reject(
    task_id: int, payload: RejectRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Отклонить задачу (rejected). Изменения не применяются."""
    return _run(lambda: service.reject_task(db, task_id, payload.reason, _uid(user)))


@router.post("/tasks/{task_id}/apply", dependencies=[Depends(require_media_curation_task_access)])
def apply(
    task_id: int, payload: ApplyRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Применить одобренную задачу (approve_tags/mark_duplicate/hide/…). Только после approved."""
    return _run(lambda: service.apply_approved_task(db, task_id, payload.action, _uid(user)))


@router.post("/tasks/{task_id}/ignore", dependencies=[Depends(require_media_curation_task_access)])
def ignore(task_id: int, db: DbSession, service: ReviewSvc, user: OptUser) -> dict[str, Any]:
    """Проигнорировать задачу (ignored)."""
    return _run(lambda: service.ignore_task(db, task_id, _uid(user)))


@router.post("/tasks/{task_id}/restore", dependencies=[Depends(require_media_curation_task_access)])
def restore(task_id: int, db: DbSession, service: ReviewSvc, user: OptUser) -> dict[str, Any]:
    """Вернуть затронутые медиа в подбор (restore). Файлы не удаляются."""
    return _run(lambda: service.restore_task_media(db, task_id, _uid(user)))
