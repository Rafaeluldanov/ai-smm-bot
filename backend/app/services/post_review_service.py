"""Сервис согласования постов (Этап 6).

Управляет жизненным циклом черновика: отправка на ревью, одобрение, отклонение,
запрос доработки, возврат в черновик, ручная правка текстов/медиа и комментарии.
Каждое действие пишется в журнал ``PostReviewAction``; смена статуса проходит
через ``post_status_service.validate_transition`` (безопасные переходы).

Реальный Telegram/AI/сеть здесь не используются: это чистая backend-логика.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.post import Post
from app.repositories import post_repository, post_review_repository
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post import PostUpdate
from app.schemas.post_review import (
    PostReviewActionCreate,
    PostReviewActionRead,
    PostReviewCard,
    PostReviewCommentRequest,
    PostReviewDecisionRequest,
    PostReviewEditRequest,
    PostReviewTimeline,
)
from app.services import post_status_service

logger = get_logger(__name__)

# Действия журнала согласования.
ACTION_SUBMIT = "submit_for_review"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_REQUEST_CHANGES = "request_changes"
ACTION_RETURN_TO_DRAFT = "return_to_draft"
ACTION_EDIT_TEXT = "edit_text"
ACTION_CHANGE_MEDIA = "change_media"
ACTION_COMMENT = "comment"

# Статусы, в которых разрешена ручная правка поста.
_EDITABLE_STATUSES: set[str] = {
    "draft",
    "needs_review",
    "changes_requested",
    "needs_media",
    "rejected",
}

# Поля поста, которые можно править вручную.
_EDITABLE_FIELDS: tuple[str, ...] = (
    "title",
    "telegram_text",
    "vk_text",
    "instagram_text",
    "hashtags",
    "seo_keywords",
    "media_asset_id",
)


class ReviewActionNotAllowedError(Exception):
    """Действие согласования недопустимо в текущем состоянии поста (API → 409)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PostReviewService:
    """Бизнес-логика согласования постов поверх репозиториев и статус-сервиса."""

    # --- Решения по посту ---

    def submit_for_review(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Отправить черновик на согласование (→ needs_review). Нужно медиа."""
        post = self._get_post(db, post_id)
        if post.media_asset_id is None:
            raise ReviewActionNotAllowedError(
                "Нельзя отправить на согласование без прикреплённого медиа"
            )
        self._apply_transition(db, post, "needs_review", ACTION_SUBMIT, request)
        return self.build_review_card(db, post_id)

    def approve_post(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Одобрить пост (→ approved)."""
        post = self._get_post(db, post_id)
        self._apply_transition(db, post, "approved", ACTION_APPROVE, request)
        return self.build_review_card(db, post_id)

    def reject_post(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Отклонить пост (→ rejected)."""
        post = self._get_post(db, post_id)
        self._apply_transition(db, post, "rejected", ACTION_REJECT, request)
        return self.build_review_card(db, post_id)

    def request_changes(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Запросить доработку (→ draft) из needs_review/approved."""
        post = self._get_post(db, post_id)
        self._apply_transition(db, post, "draft", ACTION_REQUEST_CHANGES, request)
        return self.build_review_card(db, post_id)

    def request_changes_status(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Запросить доработку с явным статусом ``changes_requested`` (v0.4.0 review-очередь).

        В отличие от :meth:`request_changes` (→ draft), оставляет пост видимым в очереди
        ревью как «нужны правки», сохраняя контекст согласования.
        """
        post = self._get_post(db, post_id)
        self._apply_transition(db, post, "changes_requested", ACTION_REQUEST_CHANGES, request)
        return self.build_review_card(db, post_id)

    def return_to_draft(
        self, db: Session, post_id: int, request: PostReviewDecisionRequest
    ) -> PostReviewCard:
        """Вернуть пост в черновик (→ draft)."""
        post = self._get_post(db, post_id)
        self._apply_transition(db, post, "draft", ACTION_RETURN_TO_DRAFT, request)
        return self.build_review_card(db, post_id)

    # --- Правка и комментарии ---

    def edit_post_texts(
        self, db: Session, post_id: int, request: PostReviewEditRequest
    ) -> PostReviewCard:
        """Вручную поправить тексты/медиа поста.

        Разрешено в статусах draft/needs_review/needs_media/rejected (нельзя
        править published/approved/scheduled). Если пост был rejected — после
        правки он переводится в draft (документировано в payload).
        """
        post = self._get_post(db, post_id)
        if post.status not in _EDITABLE_STATUSES:
            raise ReviewActionNotAllowedError(
                f"Нельзя редактировать пост в статусе '{post.status}'"
            )

        provided = request.model_dump(
            exclude_unset=True, exclude={"comment", "actor_name", "actor_role"}
        )
        changes = {field: provided[field] for field in _EDITABLE_FIELDS if field in provided}

        before: dict[str, Any] = {}
        after: dict[str, Any] = {}
        for field, value in changes.items():
            before[field] = getattr(post, field)
            after[field] = value
        if changes:
            post_repository.update_post(db, post, PostUpdate(**changes))

        from_status = post.status
        to_status = from_status
        if from_status == "rejected":
            to_status = "draft"
            post_status_service.validate_transition(from_status, to_status)
            post_repository.update_post_status(db, post.id, to_status)

        action = ACTION_CHANGE_MEDIA if set(changes) == {"media_asset_id"} else ACTION_EDIT_TEXT
        payload: dict[str, Any] = {
            "changed_fields": list(changes),
            "before": before,
            "after": after,
        }
        self._record_action(
            db,
            post,
            action,
            from_status,
            to_status,
            request.comment,
            request.actor_name,
            request.actor_role,
            payload,
        )
        return self.build_review_card(db, post_id)

    def add_comment(
        self, db: Session, post_id: int, request: PostReviewCommentRequest
    ) -> PostReviewActionRead:
        """Добавить комментарий к посту без смены статуса."""
        post = self._get_post(db, post_id)
        created = post_review_repository.create_review_action(
            db,
            PostReviewActionCreate(
                post_id=post.id,
                action=ACTION_COMMENT,
                from_status=post.status,
                to_status=post.status,
                comment=request.comment,
                actor_name=request.actor_name,
                actor_role=request.actor_role,
            ),
        )
        return PostReviewActionRead.model_validate(created)

    # --- Чтение ---

    def get_timeline(self, db: Session, post_id: int) -> PostReviewTimeline:
        """Вернуть историю действий согласования по посту."""
        post = self._get_post(db, post_id)
        actions = post_review_repository.list_review_actions(db, post_id, limit=1000)
        return PostReviewTimeline(
            post_id=post_id,
            current_status=post.status,
            actions=[PostReviewActionRead.model_validate(action) for action in actions],
        )

    def build_review_card(self, db: Session, post_id: int) -> PostReviewCard:
        """Собрать карточку поста для согласования (сводка + предупреждения)."""
        post = self._get_post(db, post_id)
        count = post_review_repository.count_review_actions(db, post_id)
        last = post_review_repository.get_last_review_action(db, post_id)

        warnings: list[str] = []
        if post.media_asset_id is None:
            warnings.append("Нет прикреплённого медиа")
        if post.status == "needs_media":
            warnings.append("Пост помечен needs_media — требуется фото/видео")
        if not (post.telegram_text and post.vk_text and post.instagram_text):
            warnings.append("Заполнены не все тексты под площадки")

        return PostReviewCard(
            post_id=post.id,
            project_id=post.project_id,
            topic_id=post.topic_id,
            media_asset_id=post.media_asset_id,
            title=post.title,
            status=post.status,
            telegram_text=post.telegram_text,
            vk_text=post.vk_text,
            instagram_text=post.instagram_text,
            hashtags=list(post.hashtags or []),
            seo_keywords=list(post.seo_keywords or []),
            review_actions_count=count,
            last_action_at=last.created_at if last is not None else None,
            warnings=warnings,
        )

    # --- Внутреннее ---

    def _get_post(self, db: Session, post_id: int) -> Post:
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)
        return post

    def _apply_transition(
        self,
        db: Session,
        post: Post,
        target: str,
        action: str,
        request: PostReviewDecisionRequest,
    ) -> None:
        """Проверить переход, сменить статус и записать действие в журнал."""
        from_status = post.status
        post_status_service.validate_transition(from_status, target)
        post_repository.update_post_status(db, post.id, target)
        self._record_action(
            db,
            post,
            action,
            from_status,
            target,
            request.comment,
            request.actor_name,
            request.actor_role,
            {},
        )
        logger.info("Пост id=%s: %s (%s -> %s)", post.id, action, from_status, target)

    def _record_action(
        self,
        db: Session,
        post: Post,
        action: str,
        from_status: str | None,
        to_status: str | None,
        comment: str | None,
        actor_name: str | None,
        actor_role: str | None,
        payload: dict[str, Any],
    ) -> None:
        post_review_repository.create_review_action(
            db,
            PostReviewActionCreate(
                post_id=post.id,
                action=action,
                from_status=from_status,
                to_status=to_status,
                comment=comment,
                actor_name=actor_name,
                actor_role=actor_role,
                payload=payload,
            ),
        )
