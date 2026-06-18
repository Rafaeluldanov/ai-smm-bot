"""REST API согласования постов (Этап 6).

Все маршруты имеют вид ``/post-reviews/{post_id}/<действие>`` — конфликтов между
ними нет. Доменные ошибки приводятся к HTTP-кодам: нет поста → 404; неизвестный
статус → 422; запрещённый переход или недопустимое действие → 409.
"""

from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_post_review_service
from app.integrations.telegram.review_interface import (
    TelegramReviewInterface,
    TelegramReviewMessage,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_review import (
    PostReviewActionRead,
    PostReviewCard,
    PostReviewCommentRequest,
    PostReviewDecisionRequest,
    PostReviewEditRequest,
    PostReviewTimeline,
)
from app.services.post_review_service import PostReviewService, ReviewActionNotAllowedError
from app.services.post_status_service import (
    InvalidPostStatusError,
    InvalidPostStatusTransitionError,
)

router = APIRouter(prefix="/post-reviews", tags=["post-reviews"])

DbSession = Annotated[Session, Depends(get_db)]
ReviewService = Annotated[PostReviewService, Depends(get_post_review_service)]

T = TypeVar("T")


def _run(action: Callable[[], T]) -> T:
    """Выполнить операцию и привести доменные ошибки к HTTP-кодам."""
    try:
        return action()
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidPostStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (InvalidPostStatusTransitionError, ReviewActionNotAllowedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# --- Чтение ---


@router.get("/{post_id}/card", response_model=PostReviewCard)
def get_card(post_id: int, db: DbSession, service: ReviewService) -> PostReviewCard:
    """Карточка поста для согласования. 404 — поста нет."""
    return _run(lambda: service.build_review_card(db, post_id))


@router.get("/{post_id}/timeline", response_model=PostReviewTimeline)
def get_timeline(post_id: int, db: DbSession, service: ReviewService) -> PostReviewTimeline:
    """История действий согласования по посту. 404 — поста нет."""
    return _run(lambda: service.get_timeline(db, post_id))


@router.get("/{post_id}/telegram-preview", response_model=TelegramReviewMessage)
def telegram_preview(post_id: int, db: DbSession, service: ReviewService) -> TelegramReviewMessage:
    """Превью карточки для Telegram (без реальной отправки). 404 — поста нет."""

    def build() -> TelegramReviewMessage:
        card = service.build_review_card(db, post_id)
        return TelegramReviewInterface().build_review_message(card)

    return _run(build)


# --- Решения ---


@router.post("/{post_id}/submit", response_model=PostReviewCard)
def submit_for_review(
    post_id: int, payload: PostReviewDecisionRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Отправить черновик на согласование. 404 — нет; 409 — переход запрещён."""
    return _run(lambda: service.submit_for_review(db, post_id, payload))


@router.post("/{post_id}/approve", response_model=PostReviewCard)
def approve_post(
    post_id: int, payload: PostReviewDecisionRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Одобрить пост. 404 — нет; 409 — переход запрещён."""
    return _run(lambda: service.approve_post(db, post_id, payload))


@router.post("/{post_id}/reject", response_model=PostReviewCard)
def reject_post(
    post_id: int, payload: PostReviewDecisionRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Отклонить пост. 404 — нет; 409 — переход запрещён."""
    return _run(lambda: service.reject_post(db, post_id, payload))


@router.post("/{post_id}/request-changes", response_model=PostReviewCard)
def request_changes(
    post_id: int, payload: PostReviewDecisionRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Запросить доработку (→ draft). 404 — нет; 409 — переход запрещён."""
    return _run(lambda: service.request_changes(db, post_id, payload))


@router.post("/{post_id}/return-to-draft", response_model=PostReviewCard)
def return_to_draft(
    post_id: int, payload: PostReviewDecisionRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Вернуть пост в черновик. 404 — нет; 409 — переход запрещён."""
    return _run(lambda: service.return_to_draft(db, post_id, payload))


@router.patch("/{post_id}/edit", response_model=PostReviewCard)
def edit_post(
    post_id: int, payload: PostReviewEditRequest, db: DbSession, service: ReviewService
) -> PostReviewCard:
    """Ручная правка текстов/медиа. 404 — нет; 409 — нельзя в текущем статусе."""
    return _run(lambda: service.edit_post_texts(db, post_id, payload))


@router.post("/{post_id}/comment", response_model=PostReviewActionRead)
def add_comment(
    post_id: int, payload: PostReviewCommentRequest, db: DbSession, service: ReviewService
) -> PostReviewActionRead:
    """Добавить комментарий (без смены статуса). 404 — поста нет."""
    return _run(lambda: service.add_comment(db, post_id, payload))
