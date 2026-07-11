"""REST API review/approval workflow (v0.4.0) — полуавтоматический режим.

Клиент видит очередь постов, открывает пост, редактирует, одобряет/отклоняет/
запрашивает правки и нажимает «Опубликовать». Все роуты — под tenant-изоляцией
(``require_project_access`` / ``require_post_access``). Реальная live-публикация
gated: кнопка «Опубликовать» отправляет пост ТОЛЬКО при всех safety gates, иначе
возвращает blocked-ответ без списания. Секретов/токенов в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_user
from app.api.security_guards import require_post_access, require_project_access
from app.models.user import User
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import PostScheduleRequest
from app.schemas.post_review import PostReviewDecisionRequest
from app.services.post_publication_service import PostNotPublishableError
from app.services.post_review_service import ReviewActionNotAllowedError
from app.services.post_status_service import (
    InvalidPostStatusError,
    InvalidPostStatusTransitionError,
)
from app.services.review_workflow_service import (
    ReviewWorkflowError,
    ReviewWorkflowService,
    get_review_workflow_service,
)

router = APIRouter(prefix="/review", tags=["review-workflow"])

DbSession = Annotated[Session, Depends(get_db)]
ReviewSvc = Annotated[ReviewWorkflowService, Depends(get_review_workflow_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    """Привести доменные ошибки к HTTP-кодам."""
    try:
        return action()
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidPostStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (
        InvalidPostStatusTransitionError,
        ReviewActionNotAllowedError,
        ReviewWorkflowError,
        PostNotPublishableError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


# --- Запросы ---


class ReviewEditRequest(BaseModel):
    """Правка текста/медиа поста из ревью."""

    title: str | None = None
    telegram_text: str | None = None
    vk_text: str | None = None
    instagram_text: str | None = None
    hashtags: list[str] | None = None
    seo_keywords: list[str] | None = None
    media_asset_id: int | None = None
    reason_tags: list[str] = Field(default_factory=list)
    actor_name: str | None = None
    actor_role: str | None = "client"


class ReviewDecisionRequest(BaseModel):
    """Решение по посту (approve/reject/request-changes)."""

    comment: str | None = None
    reason_tags: list[str] = Field(default_factory=list)
    actor_name: str | None = None
    actor_role: str | None = "client"


class ReviewRatingRequest(BaseModel):
    """Ручная оценка поста 1..5."""

    rating: int = Field(ge=1, le=5)
    reason_tags: list[str] = Field(default_factory=list)


class ReviewScheduleRequest(ReviewDecisionRequest):
    """Одобрить и запланировать публикации (без live)."""

    platforms: list[str] | None = None
    target_ids: dict[str, str] | None = None


class PublishNowRequest(BaseModel):
    """Кнопка «Опубликовать» (semi-auto). Требует явного подтверждения."""

    confirm: bool = False
    platforms: list[str] | None = None


def _decision(payload: ReviewDecisionRequest) -> PostReviewDecisionRequest:
    return PostReviewDecisionRequest(
        comment=payload.comment, actor_name=payload.actor_name, actor_role=payload.actor_role
    )


# --- Очередь и детали ---


@router.get("/projects/{project_id}/queue", dependencies=[Depends(require_project_access)])
def get_queue(
    project_id: int,
    db: DbSession,
    service: ReviewSvc,
    platform: str | None = None,
    review_status: str | None = None,
    date: str | None = None,
) -> dict[str, Any]:
    """Очередь постов на ревью со скорингом и причинами обучения."""
    return service.build_queue(db, project_id, platform, review_status, date)


@router.get("/posts/{post_id}", dependencies=[Depends(require_post_access)])
def get_post(post_id: int, db: DbSession, service: ReviewSvc) -> dict[str, Any]:
    """Детали поста для ревью: тексты, публикации, скоринг, история фидбэка."""
    return _run(lambda: service.get_post_detail(db, post_id))


# --- Решения ---


@router.post("/posts/{post_id}/edit", dependencies=[Depends(require_post_access)])
def edit_post(
    post_id: int, payload: ReviewEditRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Правка текста/медиа (событие edited, пересчёт скоринга). Live-публикации НЕТ."""
    changes = payload.model_dump(
        exclude_unset=True, exclude={"reason_tags", "actor_name", "actor_role"}
    )
    return _run(
        lambda: service.edit_post(
            db,
            post_id,
            changes,
            user_id=_uid(user),
            reason_tags=payload.reason_tags,
            actor_name=payload.actor_name,
            actor_role=payload.actor_role,
        )
    )


@router.post("/posts/{post_id}/approve", dependencies=[Depends(require_post_access)])
def approve_post(
    post_id: int, payload: ReviewDecisionRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Одобрить пост (→ approved) + сигнал обучения."""
    return _run(lambda: service.approve(db, post_id, _decision(payload), user_id=_uid(user)))


@router.post("/posts/{post_id}/reject", dependencies=[Depends(require_post_access)])
def reject_post(
    post_id: int, payload: ReviewDecisionRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Отклонить пост (→ rejected) + сигнал обучения (reason_tags)."""
    return _run(
        lambda: service.reject(
            db, post_id, _decision(payload), user_id=_uid(user), reason_tags=payload.reason_tags
        )
    )


@router.post("/posts/{post_id}/request-changes", dependencies=[Depends(require_post_access)])
def request_changes(
    post_id: int, payload: ReviewDecisionRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Запросить правки (→ changes_requested) + сигнал обучения."""
    return _run(
        lambda: service.request_changes(
            db, post_id, _decision(payload), user_id=_uid(user), reason_tags=payload.reason_tags
        )
    )


@router.post("/posts/{post_id}/rate", dependencies=[Depends(require_post_access)])
def rate_post(
    post_id: int, payload: ReviewRatingRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Ручная оценка поста 1..5 (сигнал обучения без смены статуса)."""
    return _run(
        lambda: service.rate_post(
            db, post_id, payload.rating, user_id=_uid(user), reason_tags=payload.reason_tags
        )
    )


@router.post("/posts/{post_id}/approve-and-schedule", dependencies=[Depends(require_post_access)])
def approve_and_schedule(
    post_id: int, payload: ReviewScheduleRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Одобрить и запланировать публикации (scheduled/pending). Live-публикации НЕТ."""
    schedule = None
    if payload.platforms is not None or payload.target_ids is not None:
        schedule = PostScheduleRequest(
            platforms=payload.platforms or [], target_ids=payload.target_ids
        )
    return _run(
        lambda: service.approve_and_schedule(
            db, post_id, _decision(payload), schedule=schedule, user_id=_uid(user)
        )
    )


@router.post("/posts/{post_id}/publish-now", dependencies=[Depends(require_post_access)])
def publish_now(
    post_id: int, payload: PublishNowRequest, db: DbSession, service: ReviewSvc, user: OptUser
) -> dict[str, Any]:
    """Кнопка «Опубликовать» (semi-auto). Реальная отправка — только при всех safety gates.

    Если live недоступен — blocked-ответ с причиной и БЕЗ списания units.
    """
    return _run(
        lambda: service.publish_now(
            db,
            post_id,
            confirm=payload.confirm,
            platforms=payload.platforms,
            user_id=_uid(user),
        )
    )
