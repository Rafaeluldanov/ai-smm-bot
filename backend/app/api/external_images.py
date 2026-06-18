"""REST API внешних изображений-кандидатов (Этап 9).

Статические пути (`/search`, `/search/post/{post_id}`, `/search/topic/{topic_id}`)
объявлены до динамического `/{candidate_id}`. Доменные ошибки: нет
проекта/темы/поста/кандидата → 404; неизвестный статус review → 422; запрет
конвертации → 409.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_external_image_search_service
from app.models.external_image_candidate import ExternalImageCandidate
from app.repositories import external_image_repository as repo
from app.repositories.external_image_repository import (
    ExternalImageCandidateNotFoundError,
    InvalidExternalImageReviewStatusError,
)
from app.repositories.post_repository import PostNotFoundError
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.external_image import (
    ExternalImageCandidateRead,
    ExternalImageConvertRequest,
    ExternalImageConvertResult,
    ExternalImageReviewRequest,
    ExternalImageSafetyReport,
    ExternalImageSearchRequest,
    ExternalImageSearchResult,
)
from app.services.external_image_search_service import (
    ExternalImageConversionError,
    ExternalImageSearchService,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

router = APIRouter(prefix="/external-images", tags=["external-images"])

DbSession = Annotated[Session, Depends(get_db)]
SearchService = Annotated[ExternalImageSearchService, Depends(get_external_image_search_service)]

T = TypeVar("T")


def _run(action: Callable[[], T]) -> T:
    """Привести доменные ошибки к HTTP-кодам (404/422/409)."""
    try:
        return action()
    except (
        ProjectNotFoundError,
        TopicNotFoundError,
        PostNotFoundError,
        ExternalImageCandidateNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidExternalImageReviewStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except ExternalImageConversionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- Коллекция и поиск (статические пути ДО /{candidate_id}) ---


@router.get("", response_model=list[ExternalImageCandidateRead])
def list_candidates(
    db: DbSession,
    project_id: int | None = None,
    topic_id: int | None = None,
    post_id: int | None = None,
    provider: str | None = None,
    review_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[ExternalImageCandidate]:
    """Список кандидатов с фильтрами по проекту/теме/посту/провайдеру/статусу."""
    return repo.list_candidates(
        db,
        project_id=project_id,
        topic_id=topic_id,
        post_id=post_id,
        provider=provider,
        review_status=review_status,
        limit=limit,
        offset=offset,
    )


@router.post("/search", response_model=ExternalImageSearchResult)
def search(
    payload: ExternalImageSearchRequest, db: DbSession, service: SearchService
) -> ExternalImageSearchResult:
    """Поиск внешних изображений. 404 — нет проекта/темы/поста."""
    return _run(lambda: service.search_images(db, payload))


@router.post("/search/post/{post_id}", response_model=ExternalImageSearchResult)
def search_for_post(
    post_id: int, db: DbSession, service: SearchService, limit: int = 10
) -> ExternalImageSearchResult:
    """Поиск внешних изображений под пост. 404 — нет поста."""
    return _run(lambda: service.search_for_post(db, post_id, limit=limit))


@router.post("/search/topic/{topic_id}", response_model=ExternalImageSearchResult)
def search_for_topic(
    topic_id: int, db: DbSession, service: SearchService, limit: int = 10
) -> ExternalImageSearchResult:
    """Поиск внешних изображений под тему. 404 — нет темы."""
    return _run(lambda: service.search_for_topic(db, topic_id, limit=limit))


# --- Операции над одним кандидатом (динамический {candidate_id} — последним) ---


@router.get("/{candidate_id}", response_model=ExternalImageCandidateRead)
def get_candidate(candidate_id: int, db: DbSession) -> ExternalImageCandidate:
    """Получить кандидата по id. Если нет — 404."""
    candidate = repo.get_candidate_by_id(db, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Кандидат внешнего изображения id={candidate_id} не найден",
        )
    return candidate


@router.get("/{candidate_id}/safety", response_model=ExternalImageSafetyReport)
def candidate_safety(
    candidate_id: int, db: DbSession, service: SearchService
) -> ExternalImageSafetyReport:
    """Оценка безопасности использования кандидата. 404 — нет кандидата."""
    return _run(lambda: service.get_safety_report(db, candidate_id))


@router.patch("/{candidate_id}/review", response_model=ExternalImageCandidateRead)
def review_candidate(
    candidate_id: int, payload: ExternalImageReviewRequest, db: DbSession, service: SearchService
) -> ExternalImageCandidateRead:
    """Сменить статус review. 404 — нет; 422 — неизвестный статус."""
    return _run(lambda: service.review_candidate(db, candidate_id, payload))


@router.post("/{candidate_id}/convert-to-media", response_model=ExternalImageConvertResult)
def convert_to_media(
    candidate_id: int, payload: ExternalImageConvertRequest, db: DbSession, service: SearchService
) -> ExternalImageConvertResult:
    """Конвертировать кандидата в MediaAsset. 404 — нет; 409 — нельзя."""
    return _run(lambda: service.convert_candidate_to_media_asset(db, candidate_id, payload))
