"""REST API для проектов."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.project import Project
from app.repositories import project_repository as repo
from app.repositories.project_repository import SlugAlreadyExistsError
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])

# Тип-алиас для сессии БД как зависимости (стиль FastAPI с Annotated).
DbSession = Annotated[Session, Depends(get_db)]


def _get_or_404(db: Session, project_id: int) -> Project:
    """Вернуть проект по id или поднять 404."""
    project = repo.get_project_by_id(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Проект id={project_id} не найден",
        )
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: DbSession,
    active_only: Annotated[bool, Query(description="Только активные проекты")] = True,
) -> list[Project]:
    """Список проектов."""
    return repo.list_projects(db, active_only=active_only)


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: DbSession) -> Project:
    """Создать проект. При дубле slug — 409 Conflict."""
    try:
        return repo.create_project(db, payload)
    except SlugAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/slug/{slug}", response_model=ProjectRead)
def get_project_by_slug(slug: str, db: DbSession) -> Project:
    """Получить проект по slug. Если нет — 404."""
    project = repo.get_project_by_slug(db, slug)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Проект slug='{slug}' не найден",
        )
    return project


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, db: DbSession) -> Project:
    """Получить проект по id. Если нет — 404."""
    return _get_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: DbSession) -> Project:
    """Частично обновить проект. 404 если нет, 409 если новый slug занят."""
    project = _get_or_404(db, project_id)
    try:
        return repo.update_project(db, project, payload)
    except SlugAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{project_id}/deactivate", response_model=ProjectRead)
def deactivate_project(project_id: int, db: DbSession) -> Project:
    """Деактивировать проект (is_active = False). 404 если нет."""
    project = _get_or_404(db, project_id)
    return repo.deactivate_project(db, project)
