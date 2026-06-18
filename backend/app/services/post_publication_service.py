"""Сервис планирования и публикации постов (Этап 7).

Берёт согласованный (`approved`) пост, планирует публикации по платформам и
публикует их через клиентов из ``PublicationPlatformRegistry``. Идемпотентность —
по паре (post_id, platform): повторная публикация без ``force`` не дублируется.
Ошибки платформы фиксируются в публикации (``failed`` + ``error_message``) и не
роняют весь процесс. Реальная сеть здесь не вызывается — клиенты подменяемы.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.integrations.publishing import PublishError, PublishRequest
from app.models.post import Post
from app.repositories import (
    media_asset_repository,
    post_publication_repository,
    post_repository,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import (
    DuePublicationsResult,
    PostPublicationCreate,
    PostPublicationRead,
    PostPublicationUpdate,
    PostPublishRequest,
    PostPublishResult,
    PostScheduleRequest,
)
from app.services import post_status_service
from app.services.publication_platform_registry import PublicationPlatformRegistry

logger = get_logger(__name__)

# Платформы по умолчанию, если не заданы явно и нет существующих публикаций.
_DEFAULT_PLATFORMS: tuple[str, ...] = ("telegram", "vk")

# Из каких статусов поста можно планировать / публиковать.
_SCHEDULABLE_STATUSES: set[str] = {"approved", "scheduled"}
_PUBLISHABLE_STATUSES: set[str] = {"approved", "scheduled", "published"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PostNotPublishableError(Exception):
    """Пост в статусе, из которого нельзя планировать/публиковать (API → 409)."""

    def __init__(self, post_id: int, status: str) -> None:
        self.post_id = post_id
        self.status = status
        super().__init__(
            f"Пост id={post_id} в статусе '{status}' нельзя запланировать/опубликовать"
        )


class PostPublicationService:
    """Планирование и публикация постов в Telegram/VK через реестр клиентов."""

    def __init__(
        self,
        registry: PublicationPlatformRegistry,
        default_targets: dict[str, str | None] | None = None,
    ) -> None:
        self._registry = registry
        self._default_targets = default_targets or {}

    # --- Планирование ---

    def schedule_post(
        self, db: Session, post_id: int, request: PostScheduleRequest
    ) -> PostPublishResult:
        """Запланировать публикации поста по платформам (Post → scheduled)."""
        post = self._get_publishable_post(db, post_id, _SCHEDULABLE_STATUSES)
        warnings: list[str] = []
        available = set(self._registry.get_available_platforms())

        for platform in request.platforms:
            if platform not in available:
                warnings.append(f"Платформа '{platform}' не поддерживается — пропущена")
                continue
            target_id = request.target_ids.get(platform) if request.target_ids else None
            post_publication_repository.upsert_publication_schedule(
                db, post.id, post.project_id, platform, request.scheduled_at, target_id
            )

        if request.scheduled_at is not None:
            post.scheduled_at = request.scheduled_at
        if post.status != "scheduled":
            post_status_service.validate_transition(post.status, "scheduled")
            post_repository.update_post_status(db, post.id, "scheduled")
        else:
            db.commit()

        return self._build_result(db, post_id, 0, 0, 0, warnings)

    # --- Публикация ---

    def publish_post(
        self, db: Session, post_id: int, request: PostPublishRequest | None = None
    ) -> PostPublishResult:
        """Опубликовать пост по платформам (идемпотентно, ошибки не роняют процесс)."""
        request = request or PostPublishRequest()
        post = self._get_publishable_post(db, post_id, _PUBLISHABLE_STATUSES)

        platforms = self._resolve_platforms(db, post, request.platforms)
        available = set(self._registry.get_available_platforms())

        warnings: list[str] = []
        published = failed = skipped = 0
        for platform in platforms:
            if platform not in available:
                warnings.append(f"Платформа '{platform}' не поддерживается — пропущена")
                continue
            outcome = self._publish_one(db, post, platform, request.force)
            if outcome == "published":
                published += 1
            elif outcome == "failed":
                failed += 1
            else:
                skipped += 1

        if published > 0 and failed == 0:
            self._mark_post_published(db, post_id)

        return self._build_result(db, post_id, published, failed, skipped, warnings)

    def publish_due_publications(
        self, db: Session, now: datetime | None = None
    ) -> DuePublicationsResult:
        """Опубликовать все созревшие публикации (для планировщика)."""
        moment = now or _utcnow()
        due = post_publication_repository.list_due_publications(db, moment)

        platforms_by_post: dict[int, list[str]] = {}
        for publication in due:
            platforms_by_post.setdefault(publication.post_id, []).append(publication.platform)

        result = DuePublicationsResult()
        for post_id, platforms in platforms_by_post.items():
            result.processed_posts += 1
            try:
                single = self.publish_post(
                    db, post_id, PostPublishRequest(platforms=platforms, force=False)
                )
            except (PostNotFoundError, PostNotPublishableError) as exc:
                result.warnings.append(f"Пост {post_id}: {exc}")
                continue
            result.processed_publications += len(platforms)
            result.published_count += single.published_count
            result.failed_count += single.failed_count
            result.skipped_count += single.skipped_count
            result.warnings.extend(single.warnings)

        result.warnings = list(dict.fromkeys(result.warnings))
        return result

    def build_publish_request(
        self, db: Session, post: Post, platform: str, target_id: str | None
    ) -> PublishRequest:
        """Собрать запрос на публикацию под платформу (текст, теги, attachment)."""
        text = post.telegram_text if platform == "telegram" else post.vk_text
        hashtags = list(post.hashtags or [])
        payload: dict[str, object] = {
            "post_id": post.id,
            "media_asset_id": post.media_asset_id,
            "hashtags": hashtags,
        }
        if post.media_asset_id is not None:
            asset = media_asset_repository.get_media_asset_by_id(db, post.media_asset_id)
            if asset is not None:
                payload["attachment"] = {
                    "file_name": asset.file_name,
                    "yandex_disk_path": asset.yandex_disk_path,
                }
        return PublishRequest(
            platform=platform,
            target_id=target_id,
            text=text or "",
            media_url=None,
            media_path=None,
            hashtags=hashtags,
            payload=payload,
        )

    # --- Внутреннее ---

    def _get_publishable_post(self, db: Session, post_id: int, allowed: set[str]) -> Post:
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)
        if post.status not in allowed:
            raise PostNotPublishableError(post_id, post.status)
        return post

    def _resolve_platforms(self, db: Session, post: Post, requested: list[str] | None) -> list[str]:
        if requested:
            return requested
        existing = post_publication_repository.list_publications(db, post_id=post.id)
        if existing:
            return [publication.platform for publication in existing]
        return list(_DEFAULT_PLATFORMS)

    def _publish_one(self, db: Session, post: Post, platform: str, force: bool) -> str:
        """Опубликовать одну платформу. Возвращает outcome: published/failed/skipped."""
        target_default = self._default_targets.get(platform)
        publication = post_publication_repository.get_publication_by_post_and_platform(
            db, post.id, platform
        )
        if publication is None:
            publication = post_publication_repository.create_publication(
                db,
                PostPublicationCreate(
                    post_id=post.id,
                    project_id=post.project_id,
                    platform=platform,
                    target_id=target_default,
                    status="pending",
                ),
            )

        if publication.status == "published" and not force:
            return "skipped"

        target_id = publication.target_id or target_default
        publish_request = self.build_publish_request(db, post, platform, target_id)
        publication = post_publication_repository.update_publication(
            db,
            publication,
            PostPublicationUpdate(status="publishing", attempts=publication.attempts + 1),
        )

        try:
            response = self._registry.get_client(platform).publish_post(publish_request)
        except PublishError as exc:
            post_publication_repository.update_publication(
                db, publication, PostPublicationUpdate(status="failed", error_message=str(exc))
            )
            logger.info("Публикация поста id=%s в %s не удалась: %s", post.id, platform, exc)
            return "failed"

        merged_payload = {
            **(publication.payload or {}),
            "request_text": publish_request.text,
            "raw": response.raw,
        }
        post_publication_repository.update_publication(
            db,
            publication,
            PostPublicationUpdate(
                status="published",
                external_post_id=response.external_post_id,
                external_url=response.external_url,
                published_at=_utcnow(),
                error_message=None,
                payload=merged_payload,
            ),
        )
        logger.info(
            "Пост id=%s опубликован в %s (external_id=%s)",
            post.id,
            platform,
            response.external_post_id,
        )
        return "published"

    def _mark_post_published(self, db: Session, post_id: int) -> None:
        """Перевести Post в published (через scheduled при необходимости)."""
        post = post_repository.get_post_by_id(db, post_id)
        if post is None or post.status == "published":
            return
        if post.status == "approved":
            post_status_service.validate_transition("approved", "scheduled")
            post_repository.update_post_status(db, post.id, "scheduled")
        post_status_service.validate_transition("scheduled", "published")
        updated = post_repository.update_post_status(db, post.id, "published")
        updated.published_at = _utcnow()
        db.commit()
        db.refresh(updated)

    def _build_result(
        self,
        db: Session,
        post_id: int,
        published: int,
        failed: int,
        skipped: int,
        warnings: list[str],
    ) -> PostPublishResult:
        post = post_repository.get_post_by_id(db, post_id)
        publications = post_publication_repository.list_publications(db, post_id=post_id)
        return PostPublishResult(
            post_id=post_id,
            post_status=post.status if post is not None else "unknown",
            publications=[PostPublicationRead.model_validate(p) for p in publications],
            published_count=published,
            failed_count=failed,
            skipped_count=skipped,
            warnings=warnings,
        )
