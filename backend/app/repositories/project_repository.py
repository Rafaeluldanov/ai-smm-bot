"""Репозиторий для работы с проектами (Project).

Содержит весь доступ к БД для сущности Project. Уникальность slug
проверяется явно, чтобы API мог вернуть понятный 409 Conflict
(а не ловить IntegrityError, зависящий от СУБД).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate


class SlugAlreadyExistsError(Exception):
    """Проект с таким slug уже существует."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Проект со slug '{slug}' уже существует")


def get_project_by_id(db: Session, project_id: int) -> Project | None:
    """Вернуть проект по id или None."""
    return db.get(Project, project_id)


def get_project_by_slug(db: Session, slug: str) -> Project | None:
    """Вернуть проект по slug или None."""
    return db.scalars(select(Project).where(Project.slug == slug)).first()


def list_projects(db: Session, active_only: bool = True) -> list[Project]:
    """Вернуть список проектов, при необходимости только активные."""
    stmt = select(Project).order_by(Project.id)
    if active_only:
        stmt = stmt.where(Project.is_active.is_(True))
    return list(db.scalars(stmt).all())


def list_projects_by_account(db: Session, account_id: int) -> list[Project]:
    """Вернуть проекты, привязанные к аккаунту (SaaS)."""
    stmt = select(Project).where(Project.account_id == account_id).order_by(Project.id)
    return list(db.scalars(stmt).all())


def create_project(db: Session, data: ProjectCreate) -> Project:
    """Создать проект. Бросает SlugAlreadyExistsError при дубле slug."""
    if get_project_by_slug(db, data.slug) is not None:
        raise SlugAlreadyExistsError(data.slug)

    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    """Частично обновить поля проекта.

    Обновляются только переданные поля (``exclude_unset``). При смене slug
    на уже занятый другим проектом бросает SlugAlreadyExistsError.
    """
    update_data = data.model_dump(exclude_unset=True)

    new_slug = update_data.get("slug")
    if new_slug is not None and new_slug != project.slug:
        existing = get_project_by_slug(db, new_slug)
        if existing is not None and existing.id != project.id:
            raise SlugAlreadyExistsError(new_slug)

    for field, value in update_data.items():
        setattr(project, field, value)

    db.commit()
    db.refresh(project)
    return project


def deactivate_project(db: Session, project: Project) -> Project:
    """Деактивировать проект (is_active = False), НЕ удаляя запись."""
    project.is_active = False
    db.commit()
    db.refresh(project)
    return project
