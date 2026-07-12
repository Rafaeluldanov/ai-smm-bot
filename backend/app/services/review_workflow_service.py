"""Оркестрация review/approval workflow (v0.4.0).

Полуавтоматический режим: клиент видит очередь постов (draft/needs_review/
changes_requested), открывает пост, редактирует, одобряет/отклоняет/запрашивает
правки и нажимает «Опубликовать». Каждое решение фиксируется как сигнал обучения
(:class:`ClientLearningService`) и оценивается скорингом.

БЕЗОПАСНОСТЬ:
- «Опубликовать» (publish-now) проходит через те же safety gates, что и авто-режим:
  реальная отправка возможна ТОЛЬКО если платформа поддерживает live, включён
  глобальный live-флаг и есть креды/таргет. Иначе — blocked-ответ без списания.
- секреты/токены наружу не выходят; тексты в события пишутся хешем/диффом.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    account_repository,
    post_feedback_repository,
    post_publication_repository,
    post_repository,
    project_repository,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import PostPublishRequest, PostScheduleRequest
from app.schemas.post_review import PostReviewDecisionRequest, PostReviewEditRequest
from app.services import audit_log_service as audit_actions
from app.services.billing_service import (
    USAGE_REVIEW_PUBLISH_NOW,
    BillingService,
    InsufficientBalanceError,
)

if TYPE_CHECKING:
    from app.models.post import Post
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService
    from app.services.notification_service import NotificationService
    from app.services.post_publication_service import PostPublicationService
    from app.services.post_review_service import PostReviewService

# Статус поста → тип уведомления (v0.5.0).
_POST_STATUS_NOTIFICATION_TYPE = {
    "approved": "post_approved",
    "rejected": "post_rejected",
    "changes_requested": "post_needs_review",
    "needs_review": "post_needs_review",
}

logger = get_logger(__name__)

# Статусы, попадающие в очередь ревью по умолчанию.
_QUEUE_STATUSES = ("needs_review", "changes_requested", "draft")
# Поля поста, доступные для правки из ревью.
_EDITABLE_FIELDS = (
    "title",
    "telegram_text",
    "vk_text",
    "instagram_text",
    "hashtags",
    "seo_keywords",
    "media_asset_id",
)


class ReviewWorkflowError(Exception):
    """Ошибка review workflow (напр. пост не в подходящем статусе) — API → 409."""


class ReviewWorkflowService:
    """Очередь ревью + решения + publish-now поверх review/learning/publication."""

    def __init__(
        self,
        review_service: PostReviewService | None = None,
        learning_service: ClientLearningService | None = None,
        publication_service: PostPublicationService | None = None,
        billing_service: BillingService | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._review = review_service
        self._learning = learning_service
        self._publication = publication_service
        self._billing = billing_service or BillingService()
        self._audit = audit_service

    # ------------------------------------------------------------------ #
    # Очередь и детали                                                    #
    # ------------------------------------------------------------------ #

    def build_queue(
        self,
        db: Session,
        project_id: int,
        platform: str | None = None,
        status: str | None = None,
        date: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Очередь постов проекта для ревью со скорингом и причинами обучения."""
        statuses = [status] if status else list(_QUEUE_STATUSES)
        cards: list[dict[str, Any]] = []
        for st in statuses:
            for post in post_repository.list_posts(
                db, project_id=project_id, status=st, limit=limit
            ):
                if date and (
                    post.scheduled_at is None or not post.scheduled_at.isoformat().startswith(date)
                ):
                    continue
                card = self._post_card(db, project_id, post, platform)
                if platform and card["platform"] != platform:
                    # Фильтр по платформе применяем по «основной» площадке поста.
                    continue
                cards.append(card)
        cards.sort(key=lambda c: c["post_id"])
        return {
            "project_id": project_id,
            "count": len(cards),
            "statuses": statuses,
            "items": cards,
        }

    def get_post_detail(self, db: Session, post_id: int) -> dict[str, Any]:
        """Детали поста для ревью: тексты, публикации, скоринг, история фидбэка."""
        post = self._get_post(db, post_id)
        self._audit_review(
            db, post, None, audit_actions.ACTION_REVIEW_POST_OPENED, {"post_id": post.id}
        )
        scoring = self._score(db, post)
        pubs = [
            self._publication_view(pub)
            for pub in post_publication_repository.list_publications(db, post_id=post.id)
        ]
        feedback = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "rating": e.rating,
                "reason_tags": list(e.reason_tags or []),
                "diff_summary": dict(e.diff_summary or {}),
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in post_feedback_repository.list_for_post(db, post.id)
        ]
        preview = self._publish_preview(db, post.id)
        return {
            "post_id": post.id,
            "project_id": post.project_id,
            "status": post.status,
            "title": post.title,
            "telegram_text": post.telegram_text,
            "vk_text": post.vk_text,
            "instagram_text": post.instagram_text,
            "hashtags": list(post.hashtags or []),
            "seo_keywords": list(post.seo_keywords or []),
            "media_asset_id": post.media_asset_id,
            "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
            "scoring": scoring,
            "publications": pubs,
            "feedback_events": feedback,
            "publish_gate": preview,
        }

    # ------------------------------------------------------------------ #
    # Решения                                                            #
    # ------------------------------------------------------------------ #

    def edit_post(
        self,
        db: Session,
        post_id: int,
        changes: dict[str, Any],
        user_id: int | None = None,
        reason_tags: list[str] | None = None,
        actor_name: str | None = None,
        actor_role: str | None = None,
    ) -> dict[str, Any]:
        """Правка текста/медиа: обновляет пост, пишет событие edited, пересчитывает скоринг."""
        post = self._get_post(db, post_id)
        before_text = self._primary_text(post)
        applied = {k: v for k, v in changes.items() if k in _EDITABLE_FIELDS}
        self._review_svc().edit_post_texts(
            db,
            post_id,
            PostReviewEditRequest(**applied, actor_name=actor_name, actor_role=actor_role),
        )
        db.refresh(post)
        after_text = self._primary_text(post)
        self._learning_svc().record_review_feedback(
            db,
            post_id,
            "edited",
            user_id=user_id,
            before_text=before_text,
            after_text=after_text,
            reason_tags=reason_tags,
            platform_key=self._primary_platform(post),
        )
        self._audit_review(
            db,
            post,
            user_id,
            audit_actions.ACTION_REVIEW_POST_EDITED,
            {"post_id": post.id, "changed_fields": list(applied)},
        )
        return self.get_post_detail(db, post_id)

    def approve(
        self,
        db: Session,
        post_id: int,
        request: PostReviewDecisionRequest,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Одобрить пост (→ approved) + событие approved + обновление профиля."""
        post = self._get_post(db, post_id)
        card = self._review_svc().approve_post(db, post_id, request)
        self._learning_svc().record_review_feedback(
            db, post_id, "approved", user_id=user_id, platform_key=self._primary_platform(post)
        )
        self._audit_review(
            db, post, user_id, audit_actions.ACTION_REVIEW_POST_APPROVED, {"post_id": post.id}
        )
        self._notify_post_status(db, post, "approved", user_id)
        return {"card": card.model_dump(), "status": "approved"}

    def reject(
        self,
        db: Session,
        post_id: int,
        request: PostReviewDecisionRequest,
        user_id: int | None = None,
        reason_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Отклонить пост (→ rejected) + событие rejected."""
        post = self._get_post(db, post_id)
        card = self._review_svc().reject_post(db, post_id, request)
        self._learning_svc().record_review_feedback(
            db,
            post_id,
            "rejected",
            user_id=user_id,
            reason_tags=reason_tags,
            platform_key=self._primary_platform(post),
        )
        self._audit_review(
            db, post, user_id, audit_actions.ACTION_REVIEW_POST_REJECTED, {"post_id": post.id}
        )
        self._notify_post_status(db, post, "rejected", user_id)
        return {"card": card.model_dump(), "status": "rejected"}

    def request_changes(
        self,
        db: Session,
        post_id: int,
        request: PostReviewDecisionRequest,
        user_id: int | None = None,
        reason_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Запросить правки (→ changes_requested) + событие changes_requested."""
        post = self._get_post(db, post_id)
        card = self._review_svc().request_changes_status(db, post_id, request)
        self._learning_svc().record_review_feedback(
            db,
            post_id,
            "changes_requested",
            user_id=user_id,
            reason_tags=reason_tags,
            platform_key=self._primary_platform(post),
        )
        self._audit_review(
            db,
            post,
            user_id,
            audit_actions.ACTION_REVIEW_POST_CHANGES_REQUESTED,
            {"post_id": post.id},
        )
        self._notify_post_status(db, post, "changes_requested", user_id)
        return {"card": card.model_dump(), "status": "changes_requested"}

    def approve_and_schedule(
        self,
        db: Session,
        post_id: int,
        request: PostReviewDecisionRequest,
        schedule: PostScheduleRequest | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Одобрить и запланировать публикации (scheduled/pending). Live-публикации НЕТ."""
        self.approve(db, post_id, request, user_id=user_id)
        result = self._publication_svc().schedule_post(
            db, post_id, schedule or PostScheduleRequest()
        )
        return {"status": "scheduled", "result": result.model_dump(), "live_calls": False}

    def rate_post(
        self,
        db: Session,
        post_id: int,
        rating: int,
        user_id: int | None = None,
        reason_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Ручная оценка поста (1..5) — сигнал обучения без смены статуса."""
        post = self._get_post(db, post_id)
        event = self._learning_svc().record_review_feedback(
            db,
            post_id,
            "manual_rating",
            user_id=user_id,
            rating=rating,
            reason_tags=reason_tags,
            platform_key=self._primary_platform(post),
        )
        return {"status": "ok", "event_id": event.id, "rating": event.rating}

    # ------------------------------------------------------------------ #
    # Кнопка «Опубликовать» (semi-auto) — под safety gates               #
    # ------------------------------------------------------------------ #

    def publish_now(
        self,
        db: Session,
        post_id: int,
        confirm: bool = False,
        platforms: list[str] | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """«Опубликовать» вручную. Реальная отправка — только при всех safety gates.

        Возвращает blocked-ответ с причиной (без списания), если live недоступен.
        """
        post = self._get_post(db, post_id)
        account_id = self._account_id(db, post.project_id)
        self._audit_review(
            db,
            post,
            user_id,
            audit_actions.ACTION_REVIEW_POST_PUBLISH_CLICKED,
            {"post_id": post.id},
        )

        if not confirm:
            return self._blocked(db, post, user_id, "confirmation_required", None)

        preview = self._publish_preview(db, post.id, platforms)
        sendable = [item for item in preview["items"] if item["would_send"]]
        if not sendable:
            reason = self._infer_block_reason(preview["items"])
            return self._blocked(db, post, user_id, reason, preview)

        # Баланс проверяем ДО одобрения/публикации — заблокированный по балансу
        # publish-now должен быть no-op (без смены статуса поста и без списания).
        send_platforms = [item["platform"] for item in sendable]
        units = self._billing.estimate_action_cost(USAGE_REVIEW_PUBLISH_NOW)
        if account_id is not None:
            try:
                self._billing.ensure_balance(db, account_id, units)
            except InsufficientBalanceError:
                return self._blocked(db, post, user_id, "insufficient_balance", preview)

        # --- Все gates пройдены: одобряем (клик = одобрение) и публикуем ---
        if post.status in ("needs_review", "changes_requested", "draft"):
            approve_req = PostReviewDecisionRequest(actor_role="client")
            try:
                self._review_svc().approve_post(db, post_id, approve_req)
            except Exception:  # noqa: BLE001 — уже approved/недопустимый переход не критичен
                db.rollback()

        result = self._publication_svc().publish_post(
            db, post_id, PostPublishRequest(platforms=send_platforms)
        )
        result_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        # Живой пост ушёл, если опубликована ХОТЯ БЫ одна площадка (даже при частичном
        # успехе). Списываем один раз (идемпотентно) и фиксируем факт публикации.
        published_count = int(result_dict.get("published_count", 0))
        any_published = published_count > 0
        charged = 0
        if any_published and account_id is not None:
            ledger = self._billing.debit_for_action(
                db,
                account_id,
                units=units,
                usage_type=USAGE_REVIEW_PUBLISH_NOW,
                idempotency_key=f"publish-now-{post.id}",
                project_id=post.project_id,
                post_id=post.id,
            )
            charged = units if ledger is not None else 0
        if any_published:
            self._learning_svc().record_review_feedback(
                db,
                post_id,
                "published",
                user_id=user_id,
                platform_key=self._primary_platform(post),
            )
            self._audit_review(
                db,
                post,
                user_id,
                audit_actions.ACTION_REVIEW_POST_PUBLISHED,
                {
                    "post_id": post.id,
                    "platforms": send_platforms,
                    "published_count": published_count,
                    "failed_count": int(result_dict.get("failed_count", 0)),
                },
            )
        return {
            "post_id": post.id,
            "published": any_published,
            "partial": any_published and int(result_dict.get("failed_count", 0)) > 0,
            "blocked": False,
            "units_charged": charged,
            "result": result_dict,
            "live_calls": True,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _blocked(
        self,
        db: Session,
        post: Post,
        user_id: int | None,
        reason: str,
        preview: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Собрать blocked-ответ (без публикации и без списания) + audit."""
        self._audit_review(
            db,
            post,
            user_id,
            audit_actions.ACTION_REVIEW_POST_PUBLISH_BLOCKED,
            {"post_id": post.id, "reason": reason},
        )
        return {
            "post_id": post.id,
            "published": False,
            "blocked": True,
            "reason": reason,
            "units_charged": 0,
            "publish_gate": preview or self._publish_preview(db, post.id),
            "live_calls": False,
        }

    @staticmethod
    def _infer_block_reason(items: list[dict[str, Any]]) -> str:
        """Понятная причина, почему ни одна площадка не отправит live."""
        if not items:
            return "no_target_platforms"
        if all(item["credentials_source"] == "missing" for item in items):
            return "platform_not_connected"
        if all(not item["live_enabled"] for item in items):
            return "live_disabled"
        if all(not item["token_present"] for item in items):
            return "missing_credentials"
        return "live_not_available"

    def _publish_preview(
        self, db: Session, post_id: int, platforms: list[str] | None = None
    ) -> dict[str, Any]:
        """Компактное превью safety-gates по платформам (без сети/отправки)."""
        request = PostPublishRequest(platforms=platforms) if platforms else PostPublishRequest()
        preview = self._publication_svc().preview_publication(db, post_id, request)
        items = [
            {
                "platform": item.platform,
                "would_send": item.would_send,
                "live_enabled": item.live_enabled,
                "credentials_source": item.credentials_source,
                "token_present": item.token_present,
                "target_present": bool(item.target_id),
            }
            for item in preview.items
        ]
        return {
            "post_id": preview.post_id,
            "post_status": preview.post_status,
            "items": items,
            "any_would_send": any(i["would_send"] for i in items),
            "warnings": list(preview.warnings),
        }

    def _post_card(
        self, db: Session, project_id: int, post: Post, platform: str | None
    ) -> dict[str, Any]:
        """Карточка поста для очереди ревью."""
        scoring = self._score(db, post)
        text = self._primary_text(post)
        pubs = post_publication_repository.list_publications(db, post_id=post.id)
        return {
            "post_id": post.id,
            "project_id": project_id,
            "status": post.status,
            "title": post.title,
            "platform": self._primary_platform(post),
            "text_preview": (text[:200] + "…") if len(text) > 200 else text,
            "media_count": 1 if post.media_asset_id else 0,
            "hashtags": list(post.hashtags or []),
            "scheduled_at": post.scheduled_at.isoformat() if post.scheduled_at else None,
            "quality_score": scoring["quality_score"],
            "predicted_engagement_score": scoring["predicted_engagement_score"],
            "fit_score": scoring["fit_score"],
            "learning_reasons": scoring["learning_reasons"],
            "warnings": scoring["warnings"],
            "experiment": self._experiment_info(db, post.id),
            "publications": [self._publication_view(p) for p in pubs],
        }

    @staticmethod
    def _experiment_info(db: Session, post_id: int) -> dict[str, Any] | None:
        """Если пост — вариант эксперимента, вернуть {experiment_id, title, variant_key}."""
        from app.repositories import content_experiment_repository

        variant = content_experiment_repository.get_variant_for_post(db, post_id)
        if variant is None:
            return None
        experiment = content_experiment_repository.get_experiment_by_id(db, variant.experiment_id)
        return {
            "experiment_id": variant.experiment_id,
            "variant_id": variant.id,
            "variant_key": variant.variant_key,
            "title": experiment.title if experiment is not None else None,
            "is_winner": variant.is_winner,
        }

    def _score(self, db: Session, post: Post) -> dict[str, Any]:
        return self._learning_svc().score_content_candidate(
            db, post.project_id, self._primary_platform(post), post
        )

    @staticmethod
    def _publication_view(pub: Any) -> dict[str, Any]:
        return {
            "id": pub.id,
            "platform": pub.platform,
            "status": pub.status,
            "scheduled_at": pub.scheduled_at.isoformat() if pub.scheduled_at else None,
            "published_at": pub.published_at.isoformat() if pub.published_at else None,
        }

    @staticmethod
    def _primary_text(post: Post) -> str:
        for attr in ("vk_text", "telegram_text", "instagram_text"):
            value = getattr(post, attr, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _primary_platform(post: Post) -> str | None:
        if post.vk_text:
            return "vk"
        if post.telegram_text:
            return "telegram"
        if post.instagram_text:
            return "instagram"
        return None

    def _get_post(self, db: Session, post_id: int) -> Post:
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)
        return post

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _notify_post_status(
        self, db: Session, post: Post, status: str, user_id: int | None
    ) -> None:
        """Уведомить владельца проекта о смене статуса поста (безопасно; skip если некому)."""
        try:
            ntype = _POST_STATUS_NOTIFICATION_TYPE.get(status)
            if ntype is None:
                return
            account_id = self._account_id(db, post.project_id)
            recipient = None
            if account_id is not None:
                account = account_repository.get_account_by_id(db, account_id)
                recipient = account.owner_user_id if account is not None else None
            if recipient is None or recipient == user_id:
                return  # некому или сам инициатор — пропускаем
            self._notify().create_notification(
                db,
                recipient_user_id=recipient,
                notification_type=ntype,
                title=f"Пост #{post.id}: {status}",
                message=f"Статус поста #{post.id} изменён на «{status}».",
                account_id=account_id,
                project_id=post.project_id,
                actor_user_id=user_id,
                entity_type="post",
                entity_id=post.id,
                action_url=f"/ui/projects/{post.project_id}/review",
            )
        except Exception:  # noqa: BLE001 — уведомление не критично для ревью
            logger.warning("post review notification failed post_id=%s", post.id, exc_info=False)

    def _notify(self) -> NotificationService:
        if getattr(self, "_notifications", None) is None:
            from app.services.notification_service import NotificationService

            self._notifications = NotificationService()
        return self._notifications

    # --- Ленивое построение зависимостей (без циклических импортов) ---

    def _review_svc(self) -> PostReviewService:
        if self._review is None:
            from app.services.post_review_service import PostReviewService

            self._review = PostReviewService()
        return self._review

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _publication_svc(self) -> PostPublicationService:
        if self._publication is None:
            from app.api.deps import (
                get_post_publication_service,
                get_publication_platform_registry,
            )

            self._publication = get_post_publication_service(get_publication_platform_registry())
        return self._publication

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _audit_review(
        self, db: Session, post: Post, user_id: int | None, action: str, metadata: dict[str, Any]
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=self._account_id(db, post.project_id),
            user_id=user_id,
            project_id=post.project_id,
            entity_type="post",
            entity_id=post.id,
            metadata=metadata,
        )


def get_review_workflow_service() -> ReviewWorkflowService:
    """DI-фабрика оркестратора review workflow."""
    return ReviewWorkflowService()
