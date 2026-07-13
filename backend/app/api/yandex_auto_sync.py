"""REST API авто-синхронизации Яндекс Диска — v0.5.7.

Клиентский слой «медиа синхронизируется само»: дашборд, профиль, health-check, preview, run
(dry-run по умолчанию), pause/resume, история прогонов. Всё под project-гардом. Секретов/сырых
токенов/внутренних путей в ответах нет; реальной сети/удаления файлов/live-публикаций нет.
Эндпоинта удаления НЕТ.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_yandex_auto_sync_service
from app.api.security_guards import require_project_access
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import yandex_auto_sync_repository as sync_repo
from app.services.yandex_auto_sync_service import YandexAutoSyncError, YandexAutoSyncService

router = APIRouter(prefix="/yandex-sync", tags=["yandex-sync"])

DbSession = Annotated[Session, Depends(get_db)]
SyncSvc = Annotated[YandexAutoSyncService, Depends(get_yandex_auto_sync_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except YandexAutoSyncError as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class ProfileRequest(BaseModel):
    """Настройка профиля синхронизации (упрощённая клиентская форма)."""

    public_url: str | None = None
    root_folder: str | None = None
    default_tags: list[str] | None = None
    allowed_folders: list[str] | None = None
    sync_frequency_minutes: int | None = None
    is_enabled: bool | None = None


class PreviewRequest(BaseModel):
    """Предпросмотр синхронизации."""

    limit: int | None = None


class RunRequest(BaseModel):
    """Запуск синхронизации."""

    dry_run: bool = True


# --- Роуты (project-scoped) ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд авто-синхронизации проекта."""
    return _run(lambda: service.build_dashboard(db, project_id))


@router.get("/projects/{project_id}/profile", dependencies=[Depends(require_project_access)])
def get_profile(
    project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser
) -> dict[str, Any]:
    """Профиль синхронизации (public view; url — маской)."""
    profile = _run(lambda: service.get_or_create_profile(db, project_id, current_user_id=user.id))
    return sync_repo.public_profile_view(profile)


@router.post("/projects/{project_id}/profile", dependencies=[Depends(require_project_access)])
def configure_profile(
    project_id: int,
    payload: ProfileRequest,
    db: DbSession,
    service: SyncSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Сохранить настройки профиля синхронизации."""
    return _run(
        lambda: service.configure_profile(
            db, project_id, payload.model_dump(exclude_none=True), current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/health-check", dependencies=[Depends(require_project_access)])
def health_check(
    project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser
) -> dict[str, Any]:
    """Проверка готовности синхронизации (блокеры)."""
    return _run(lambda: service.health_check(db, project_id))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int,
    payload: PreviewRequest,
    db: DbSession,
    service: SyncSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Предпросмотр синхронизации (без записи, без сети по умолчанию)."""
    return _run(
        lambda: service.preview_sync(db, project_id, limit=payload.limit, current_user_id=user.id)
    )


@router.post("/projects/{project_id}/run-dry", dependencies=[Depends(require_project_access)])
def run_dry(project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser) -> dict[str, Any]:
    """Синхронизация в DRY-RUN (без записи медиа, без сети)."""
    return _run(lambda: service.run_sync(db, project_id, dry_run=True, current_user_id=user.id))


@router.post("/projects/{project_id}/run", dependencies=[Depends(require_project_access)])
def run(
    project_id: int,
    payload: RunRequest,
    db: DbSession,
    service: SyncSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Запустить синхронизацию (реальная запись — только при network + dry_run=false)."""
    return _run(
        lambda: service.run_sync(db, project_id, dry_run=payload.dry_run, current_user_id=user.id)
    )


@router.post("/projects/{project_id}/pause", dependencies=[Depends(require_project_access)])
def pause(project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser) -> dict[str, Any]:
    """Поставить синхронизацию на паузу."""
    return _run(lambda: service.pause_sync(db, project_id, current_user_id=user.id))


@router.post("/projects/{project_id}/resume", dependencies=[Depends(require_project_access)])
def resume(project_id: int, db: DbSession, service: SyncSvc, user: CurrentUser) -> dict[str, Any]:
    """Возобновить синхронизацию."""
    return _run(lambda: service.resume_sync(db, project_id, current_user_id=user.id))


@router.get("/projects/{project_id}/runs", dependencies=[Depends(require_project_access)])
def list_runs(project_id: int, db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """История прогонов синхронизации (public view)."""
    return [
        sync_repo.public_run_view(r)
        for r in sync_repo.list_runs_for_project(db, project_id, limit=50)
    ]


# --- Worker (admin/local) ---


@router.post("/worker/tick-dry")
def worker_tick_dry(db: DbSession, service: SyncSvc, user: CurrentUser) -> dict[str, Any]:
    """DRY-RUN tick воркера синхронизации (требует авторизации). Без сети/записи по умолчанию."""
    return service.run_worker_tick(db, dry_run=True)
