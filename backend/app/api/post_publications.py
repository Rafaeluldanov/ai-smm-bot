"""REST API публикаций поста (Этап 7).

Статические пути (``/schedule/...``, ``/publish/...``, ``/publish-due``) объявлены
до динамического ``/{publication_id}``. Доменные ошибки: нет поста/публикации →
404; пост в неподходящем статусе → 409. Ошибки конкретной платформы не роняют
запрос — они фиксируются в публикации (``failed``).
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_post_publication_service
from app.models.post_publication import PostPublication
from app.repositories import post_publication_repository as repo
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import (
    DuePublicationsResult,
    PostPublicationRead,
    PostPublicationUpdate,
    PostPublishRequest,
    PostPublishResult,
    PostScheduleRequest,
    PublishDueRequest,
)
from app.services.post_publication_service import (
    PostNotPublishableError,
    PostPublicationService,
)

router = APIRouter(prefix="/post-publications", tags=["post-publications"])

DbSession = Annotated[Session, Depends(get_db)]
PublicationService = Annotated[PostPublicationService, Depends(get_post_publication_service)]


def _post_404_409(action: Callable[[], PostPublishResult]) -> PostPublishResult:
    """Привести доменные ошибки публикации к HTTP-кодам (404/409)."""
    try:
        return action()
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PostNotPublishableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- Коллекция и операции (статические пути ДО /{publication_id}) ---


@router.get("", response_model=list[PostPublicationRead])
def list_publications(
    db: DbSession,
    post_id: int | None = None,
    project_id: int | None = None,
    platform: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PostPublication]:
    """Список публикаций с фильтрами по посту, проекту, платформе и статусу."""
    return repo.list_publications(
        db,
        post_id=post_id,
        project_id=project_id,
        platform=platform,
        status=status_filter,
        limit=limit,
        offset=offset,
    )


@router.post("/schedule/{post_id}", response_model=PostPublishResult)
def schedule_post(
    post_id: int, payload: PostScheduleRequest, db: DbSession, service: PublicationService
) -> PostPublishResult:
    """Запланировать публикации поста. 404 — нет поста; 409 — статус не тот."""
    return _post_404_409(lambda: service.schedule_post(db, post_id, payload))


@router.post("/publish/{post_id}", response_model=PostPublishResult)
def publish_post(
    post_id: int,
    db: DbSession,
    service: PublicationService,
    payload: PostPublishRequest | None = None,
) -> PostPublishResult:
    """Опубликовать пост. 404 — нет поста; 409 — статус не тот."""
    request = payload or PostPublishRequest()
    return _post_404_409(lambda: service.publish_post(db, post_id, request))


@router.post("/publish-due", response_model=DuePublicationsResult)
def publish_due(
    db: DbSession,
    service: PublicationService,
    payload: PublishDueRequest | None = None,
) -> DuePublicationsResult:
    """Опубликовать все созревшие публикации (планировщик вручную)."""
    now = payload.now if payload is not None else None
    return service.publish_due_publications(db, now)


# --- Операции над одной публикацией (динамический {publication_id} — последним) ---


@router.get("/{publication_id}", response_model=PostPublicationRead)
def get_publication(publication_id: int, db: DbSession) -> PostPublication:
    """Получить публикацию по id. Если нет — 404."""
    publication = repo.get_publication_by_id(db, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Публикация id={publication_id} не найдена",
        )
    return publication


@router.patch("/{publication_id}", response_model=PostPublicationRead)
def update_publication(
    publication_id: int, payload: PostPublicationUpdate, db: DbSession
) -> PostPublication:
    """Ручная правка публикации (target_id/status/error_message и пр.). 404 — нет."""
    publication = repo.get_publication_by_id(db, publication_id)
    if publication is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Публикация id={publication_id} не найдена",
        )
    return repo.update_publication(db, publication, payload)
