"""REST API для тем и недельного контент-плана."""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_topic_selection_service
from app.models.topic import Topic
from app.repositories import topic_repository as repo
from app.repositories.topic_repository import (
    InvalidTopicStatusError,
    TopicNotFoundError,
)
from app.schemas.topic import (
    TopicRead,
    TopicSelectionRequest,
    TopicSelectionResult,
    TopicStatusUpdate,
    WeeklyContentPlan,
)
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/topics", tags=["topics"])

DbSession = Annotated[Session, Depends(get_db)]
TopicService = Annotated[TopicSelectionService, Depends(get_topic_selection_service)]

T = TypeVar("T")


def _project_404(action: Callable[[], T]) -> T:
    """Обернуть операцию: ProjectNotFoundError -> 404."""
    try:
        return action()
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Коллекция и операции выбора (статические пути ДО /{topic_id}) ---


@router.get("", response_model=list[TopicRead])
def list_topics(
    db: DbSession,
    project_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    cluster: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Topic]:
    """Список тем с фильтрами по проекту, статусу и кластеру."""
    return repo.list_topics(
        db, project_id=project_id, status=status_filter, cluster=cluster, limit=limit, offset=offset
    )


@router.post("/select/project/{project_id}", response_model=TopicSelectionResult)
def select_by_project(
    project_id: int, payload: TopicSelectionRequest, db: DbSession, service: TopicService
) -> TopicSelectionResult:
    """Выбрать темы для проекта по id. 404 — проекта нет."""
    return _project_404(lambda: service.select_topics_for_project(db, project_id, payload))


@router.post("/select/slug/{slug}", response_model=TopicSelectionResult)
def select_by_slug(
    slug: str, payload: TopicSelectionRequest, db: DbSession, service: TopicService
) -> TopicSelectionResult:
    """Выбрать темы для проекта по slug. 404 — проекта нет."""
    return _project_404(lambda: service.select_topics_for_project_slug(db, slug, payload))


@router.post("/weekly-plan/project/{project_id}", response_model=WeeklyContentPlan)
def weekly_plan_by_project(
    project_id: int, payload: TopicSelectionRequest, db: DbSession, service: TopicService
) -> WeeklyContentPlan:
    """Построить недельный контент-план по id проекта. 404 — проекта нет."""
    return _project_404(lambda: service.build_weekly_content_plan(db, project_id, payload))


@router.post("/weekly-plan/slug/{slug}", response_model=WeeklyContentPlan)
def weekly_plan_by_slug(
    slug: str, payload: TopicSelectionRequest, db: DbSession, service: TopicService
) -> WeeklyContentPlan:
    """Построить недельный контент-план по slug проекта. 404 — проекта нет."""
    return _project_404(lambda: service.build_weekly_content_plan_by_slug(db, slug, payload))


# --- Операции над одной темой (динамический {topic_id} — последним) ---


@router.get("/{topic_id}", response_model=TopicRead)
def get_topic(topic_id: int, db: DbSession) -> Topic:
    """Получить тему по id. Если нет — 404."""
    topic = repo.get_topic_by_id(db, topic_id)
    if topic is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Тема id={topic_id} не найдена"
        )
    return topic


@router.patch("/{topic_id}/status", response_model=TopicRead)
def update_topic_status(topic_id: int, payload: TopicStatusUpdate, db: DbSession) -> Topic:
    """Сменить статус темы. 404 — нет темы; 422 — неизвестный статус."""
    try:
        return repo.mark_topic_status(db, topic_id, payload.status)
    except InvalidTopicStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except TopicNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
