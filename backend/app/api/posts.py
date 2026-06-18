"""REST API для постов и их генерации (Этап 5).

Статические пути (``/posts/generate/...``) объявляются ДО динамического
``/posts/{post_id}``, чтобы не перехватывать их параметром пути.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_post_generation_service
from app.models.post import Post
from app.repositories import post_repository as repo
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.post import (
    PostGenerationRequest,
    PostGenerationResult,
    PostRead,
    PostStatusUpdate,
    PostUpdate,
    WeeklyPostGenerationRequest,
    WeeklyPostGenerationResult,
)
from app.services.post_generation_service import PostGenerationService
from app.services.post_status_service import (
    InvalidPostStatusTransitionError,
    get_allowed_post_statuses,
    validate_transition,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/posts", tags=["posts"])

DbSession = Annotated[Session, Depends(get_db)]
PostService = Annotated[PostGenerationService, Depends(get_post_generation_service)]


# --- Коллекция и генерация (статические пути ДО /{post_id}) ---


@router.get("", response_model=list[PostRead])
def list_posts(
    db: DbSession,
    project_id: int | None = None,
    topic_id: int | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Post]:
    """Список постов с фильтрами по проекту, теме и статусу."""
    return repo.list_posts(
        db,
        project_id=project_id,
        topic_id=topic_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("/generate/topic/{topic_id}", response_model=PostGenerationResult)
def generate_post_for_topic(
    topic_id: int,
    db: DbSession,
    service: PostService,
    payload: PostGenerationRequest | None = None,
) -> PostGenerationResult:
    """Сгенерировать черновик поста по теме. 404 — темы нет."""
    request = payload or PostGenerationRequest()
    try:
        return service.generate_post_for_topic(db, topic_id, request)
    except (TopicNotFoundError, ProjectNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/generate/weekly-plan", response_model=WeeklyPostGenerationResult)
def generate_weekly_posts(
    payload: WeeklyPostGenerationRequest, db: DbSession, service: PostService
) -> WeeklyPostGenerationResult:
    """Сгенерировать посты на неделю(и) из рекомендованных тем. 404 — проекта нет."""
    try:
        return service.generate_weekly_posts(db, payload)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Операции над одним постом (динамический {post_id} — последним) ---


@router.get("/{post_id}", response_model=PostRead)
def get_post(post_id: int, db: DbSession) -> Post:
    """Получить пост по id. Если нет — 404."""
    post = repo.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Пост id={post_id} не найден"
        )
    return post


@router.patch("/{post_id}", response_model=PostRead)
def update_post(post_id: int, payload: PostUpdate, db: DbSession) -> Post:
    """Ручная правка поста (тексты, хэштеги, SEO, медиа). 404 — поста нет."""
    post = repo.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Пост id={post_id} не найден"
        )
    return repo.update_post(db, post, payload)


@router.patch("/{post_id}/status", response_model=PostRead)
def update_post_status(post_id: int, payload: PostStatusUpdate, db: DbSession) -> Post:
    """Сменить статус поста. 404 — нет; 422 — неизвестный статус; 409 — запрещён переход."""
    new_status = payload.status
    if new_status not in get_allowed_post_statuses():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Неизвестный статус поста: '{new_status}'",
        )
    post = repo.get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Пост id={post_id} не найден"
        )
    try:
        validate_transition(post.status, new_status)
    except InvalidPostStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return repo.update_post_status(db, post_id, new_status)
