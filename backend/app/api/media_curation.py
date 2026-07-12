"""REST API курирования медиатеки (v0.4.8).

Все роуты — под tenant-изоляцией. Preview/генерация/применение — бесплатны (без внешнего AI).
Теги применяются ТОЛЬКО после подтверждения; файлы НЕ удаляются (нет delete-роута). Секретов
и внутренних путей к файлам в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_media_curation_service, get_optional_user
from app.api.security_guards import require_media_curation_task_access, require_project_access
from app.models.user import User
from app.repositories import media_curation_repository
from app.services.media_curation_service import MediaCurationError, MediaCurationService

router = APIRouter(prefix="/media-curation", tags=["media-curation"])

DbSession = Annotated[Session, Depends(get_db)]
CurSvc = Annotated[MediaCurationService, Depends(get_media_curation_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except MediaCurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


# --- Запросы ---


class PreviewRequest(BaseModel):
    """Предпросмотр задач курирования."""

    platform_key: str | None = None
    limit: int = 100


class GenerateRequest(BaseModel):
    """Генерация задач курирования."""

    platform_key: str | None = None
    dry_run: bool = False


class ApplyRequest(BaseModel):
    """Применение задачи: approve_tags | mark_duplicate | hide_from_selection | ..."""

    action: str = "mark_reviewed"


class RejectRequest(BaseModel):
    """Отклонение задачи."""

    reason: str | None = None


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_tasks(
    project_id: int,
    db: DbSession,
    service: CurSvc,
    task_status: str | None = None,
    task_type: str | None = None,
    media_asset_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список задач курирования проекта (фильтры статус/тип/медиа)."""
    rows = media_curation_repository.list_tasks_for_project(
        db, project_id, task_status, task_type, media_asset_id, limit, offset
    )
    return [service._task_view(t) for t in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: CurSvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Сводка курирования медиатеки проекта для UI."""
    return service.build_curation_dashboard(db, project_id, _platform(platform_key))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int, payload: PreviewRequest, db: DbSession, service: CurSvc
) -> dict[str, Any]:
    """Предпросмотр предлагаемых задач курирования (без записи)."""
    return _run(
        lambda: service.preview_curation_tasks(
            db, project_id, _platform(payload.platform_key), limit=payload.limit
        )
    )


@router.post("/projects/{project_id}/generate", dependencies=[Depends(require_project_access)])
def generate(
    project_id: int, payload: GenerateRequest, db: DbSession, service: CurSvc, user: OptUser
) -> dict[str, Any]:
    """Создать задачи курирования (пишет при dry_run=false; без авто-apply/hide/delete)."""
    return _run(
        lambda: service.generate_curation_tasks(
            db,
            project_id,
            _platform(payload.platform_key),
            dry_run=payload.dry_run,
            current_user_id=_uid(user),
        )
    )


@router.post(
    "/projects/{project_id}/media-assets/{media_asset_id}/restore",
    dependencies=[Depends(require_project_access)],
)
def restore_media(
    project_id: int, media_asset_id: int, db: DbSession, service: CurSvc, user: OptUser
) -> dict[str, Any]:
    """Вернуть медиа в подбор (selectable). Файл не удаляется."""
    return _run(lambda: service.restore_media(db, project_id, media_asset_id, _uid(user)))


# --- Роуты задачи ---


@router.get("/tasks/{task_id}", dependencies=[Depends(require_media_curation_task_access)])
def get_task(task_id: int, db: DbSession, service: CurSvc) -> dict[str, Any]:
    """Одна задача курирования."""
    task = media_curation_repository.get_task_by_id(db, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return service._task_view(task)


@router.post("/tasks/{task_id}/apply", dependencies=[Depends(require_media_curation_task_access)])
def apply_task(
    task_id: int, payload: ApplyRequest, db: DbSession, service: CurSvc, user: OptUser
) -> dict[str, Any]:
    """Применить задачу (approve_tags/mark_duplicate/hide/restore/ignore_cluster/mark_reviewed)."""
    return _run(lambda: service.apply_task(db, task_id, payload.action, _uid(user)))


@router.post("/tasks/{task_id}/reject", dependencies=[Depends(require_media_curation_task_access)])
def reject_task(
    task_id: int, payload: RejectRequest, db: DbSession, service: CurSvc, user: OptUser
) -> dict[str, Any]:
    """Отклонить задачу (без изменений медиа)."""
    return _run(lambda: service.reject_task(db, task_id, payload.reason, _uid(user)))


@router.post("/tasks/{task_id}/ignore", dependencies=[Depends(require_media_curation_task_access)])
def ignore_task(task_id: int, db: DbSession, service: CurSvc, user: OptUser) -> dict[str, Any]:
    """Проигнорировать задачу."""
    return _run(lambda: service.ignore_task(db, task_id, _uid(user)))
