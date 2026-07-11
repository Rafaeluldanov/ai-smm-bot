"""Сервис планирования и публикации постов (Этап 7).

Берёт согласованный (`approved`) пост, планирует публикации по платформам и
публикует их через клиентов из ``PublicationPlatformRegistry``. Идемпотентность —
по паре (post_id, platform): повторная публикация без ``force`` не дублируется.
Ошибки платформы фиксируются в публикации (``failed`` + ``error_message``) и не
роняют весь процесс. Реальная сеть здесь не вызывается — клиенты подменяемы.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.logging import get_logger
from app.integrations import platform_capabilities
from app.integrations.platform_capabilities import PlatformCapabilities
from app.integrations.publishing import PublishError, PublishRequest
from app.models.media_asset import MediaAsset
from app.models.post import Post
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    post_publication_repository,
    post_repository,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post_publication import (
    DuePublicationsResult,
    PlatformCapabilitiesRead,
    PostPublicationCreate,
    PostPublicationRead,
    PostPublicationUpdate,
    PostPublishPreview,
    PostPublishRequest,
    PostPublishResult,
    PostScheduleRequest,
    PublicationPreviewItem,
)
from app.services import post_status_service
from app.services.publication_platform_registry import PublicationPlatformRegistry

logger = get_logger(__name__)

# Платформы по умолчанию, если не заданы явно и нет существующих публикаций.
_DEFAULT_PLATFORMS: tuple[str, ...] = ("telegram", "vk")

# Расширения видео: на этом этапе видео не загружается как вложение.
_VIDEO_EXTENSIONS: frozenset[str] = frozenset({"mov", "mp4", "m4v", "avi", "mkv", "webm"})


def _media_kind(file_name: str | None) -> str:
    """Определить тип медиа по имени файла: ``image`` | ``video`` | ``none``."""
    if not file_name:
        return "none"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return "video" if ext in _VIDEO_EXTENSIONS else "image"


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
        """Собрать запрос на публикацию под платформу (текст, теги, медиа).

        Текст берётся под платформу (``telegram_text``/``vk_text``). Медиа: если у
        актива есть одобренный (``approved``) улучшенный вариант — предпочитаем путь
        к улучшенной копии (``preferred_media_path``); иначе используем метаданные
        оригинала.
        """
        text = self._platform_text(post, platform)
        hashtags = list(post.hashtags or [])
        settings = get_settings()
        notes = post.generation_notes or {}
        # Креды публикации резолвятся из подключения проекта (БД) → env-fallback (local) →
        # missing. Токен НЕ кладём в payload — только источник и факт наличия. Если у
        # подключения есть external_id, а target не задан — используем его.
        from app.services.platform_connection_service import PlatformConnectionService

        creds = PlatformConnectionService().resolve_publish_credentials(
            db, post.project_id, platform
        )
        if target_id is None and creds.external_id:
            target_id = creds.external_id
        payload: dict[str, object] = {
            "post_id": post.id,
            "media_asset_id": post.media_asset_id,
            "credentials_source": creds.source,
            "token_present": creds.token_present,
            "hashtags": hashtags,
            "media_source": "none",
            "media_kind": "none",
            "media_count": 0,
            "media_asset_ids": [post.media_asset_id] if post.media_asset_id is not None else [],
            "preferred_media_path": None,
            # VK API стратегия загрузки фото (из настроек; album_id — опционально).
            "vk_photo_upload_strategy": settings.vk_photo_upload_strategy,
            "vk_photo_album_id": settings.vk_photo_album_id,
            "vk_photo_album_title": settings.vk_photo_album_title,
            # media_policy=media_group ⇒ картинки обязательны (нет text-only фолбэка).
            "media_policy": notes.get("media_policy"),
        }
        media_path: str | None = None
        if post.media_asset_id is not None:
            asset = media_asset_repository.get_media_asset_by_id(db, post.media_asset_id)
            if asset is not None:
                media_path, media_source, variant_id = self._preferred_media(db, asset)
                payload["media_source"] = media_source
                # Тип медиа определяем по файлу, который реально пойдёт во вложение:
                # улучшенная копия (media_path) или оригинал (asset.file_name).
                single_kind = _media_kind(media_path or asset.file_name)
                payload["media_kind"] = single_kind
                payload["media_count"] = 0 if single_kind == "none" else 1
                payload["preferred_media_path"] = media_path
                payload["attachment"] = {
                    "file_name": asset.file_name,
                    "yandex_disk_path": asset.yandex_disk_path,
                }
                if variant_id is not None:
                    payload["variant_id"] = variant_id

        # Группа медиа (v0.1.14): если пост создан по группе, в generation_notes
        # лежит media_asset_ids>1 — собираем несколько вложений (media_items).
        # Одиночный media_asset_id продолжает работать по старому пути.
        group_ids = self._group_media_asset_ids(post)
        if len(group_ids) > 1:
            media_items = self._build_media_items(db, group_ids)
            if media_items:
                payload["media_items"] = media_items
                payload["media_asset_ids"] = [item["id"] for item in media_items]
                payload["media_kind"] = self._group_media_kind(media_items)
                payload["media_count"] = len(media_items)
                first_image = next(
                    (item for item in media_items if item.get("media_kind") == "image"), None
                )
                if first_image is not None:
                    payload["media_source"] = first_image["media_source"]
                    payload["preferred_media_path"] = first_image["media_path"]
        return PublishRequest(
            platform=platform,
            target_id=target_id,
            text=text or "",
            media_url=None,
            media_path=media_path,
            hashtags=hashtags,
            payload=payload,
        )

    def preview_publication(
        self, db: Session, post_id: int, request: PostPublishRequest | None = None
    ) -> PostPublishPreview:
        """Dry-run preview: показать payload публикации по платформам БЕЗ отправки."""
        request = request or PostPublishRequest()
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)

        platforms = self._resolve_platforms(db, post, request.platforms)
        available = set(self._registry.get_available_platforms())

        items: list[PublicationPreviewItem] = []
        warnings: list[str] = []
        for platform in platforms:
            if platform not in available:
                warnings.append(f"Платформа '{platform}' не поддерживается — пропущена")
                continue
            target_id = self._resolve_preview_target(db, post.id, platform)
            publish_request = self.build_publish_request(db, post, platform, target_id)
            client = self._registry.get_client(platform)
            live_enabled = bool(getattr(client, "live_enabled", False))
            live_implemented = bool(getattr(client, "live_implemented", True))
            payload = publish_request.payload
            media_source = str(payload.get("media_source", "none"))
            media_kind = str(payload.get("media_kind", "none"))
            media_count = int(payload.get("media_count", 0) or 0)
            media_asset_ids = [
                value for value in (payload.get("media_asset_ids") or []) if isinstance(value, int)
            ]

            caps = platform_capabilities.get_capabilities(platform)
            effective = self._effective_media_items(payload)
            route = platform_capabilities.route_media(caps, effective) if caps is not None else None

            media_items = payload.get("media_items")
            group_has_image = isinstance(media_items, list) and any(
                str(item.get("media_kind")) == "image" for item in media_items
            )
            group_has_video = isinstance(media_items, list) and any(
                str(item.get("media_kind")) == "video" for item in media_items
            )

            item_warnings: list[str] = []
            unsupported_media_reason = route.unsupported_media_reason if route is not None else None
            upload_strategy: str | None = None
            would_prepare_media = False
            needs_public_image_url = False
            # VK/Telegram — live-ready фото; сохраняем прежнее решение и точные тексты
            # предупреждений. Остальные платформы — решение из capability-слоя.
            if platform == "vk":
                would_attach_media = media_kind in {"image", "image_group", "mixed"}
                # Стратегия загрузки фото VK — из payload (dry-run сеть не вызывает).
                upload_strategy = str(payload.get("vk_photo_upload_strategy") or "auto")
                if group_has_video:
                    item_warnings.append("VK video upload is not implemented; video skipped")
                elif media_kind == "video":
                    item_warnings.append(
                        f"Видео ({post.media_asset_id}) не прикрепляется — уйдёт только текст"
                    )
                # would_attach_media только если есть image-медиа; иначе — причина text-only.
                if would_attach_media:
                    unsupported_media_reason = None
                else:
                    unsupported_media_reason = unsupported_media_reason or (
                        "У поста нет image-медиа для VK — уйдёт только текст"
                    )
                item_warnings.extend(self._limit_warnings(route, item_warnings))
            elif platform == "telegram":
                would_attach_media = group_has_image
                if group_has_video:
                    item_warnings.append("Telegram video upload is not implemented; video skipped")
                elif media_kind == "image" and not group_has_image:
                    # Одиночное фото (не медиа-группа) сейчас уходит text-only — honest dry-run.
                    unsupported_media_reason = (
                        "Telegram: одиночное фото прикрепляется только в составе медиа-группы "
                        "— уйдёт только текст"
                    )
                    item_warnings.append(unsupported_media_reason)
                item_warnings.extend(self._limit_warnings(route, item_warnings))
            elif platform == "instagram":
                # Instagram Graph API публикует НЕ локальный файл, а публичный HTTPS
                # image_url. Capability-слой решает would_attach_media (photo/carousel);
                # добавляем honest-флаги: медиа будет подготовлено, но нужен публичный
                # URL. Сеть/Meta API не вызываются — это dry-run.
                would_attach_media = route.would_attach_media if route is not None else False
                if route is not None:
                    item_warnings.extend(route.media_warnings)
                if media_kind in {"image", "image_group", "mixed"}:
                    would_prepare_media = True
                    needs_public_image_url = True
                    item_warnings.append(
                        "Instagram API публикует не локальный файл, а публичный HTTPS "
                        "image_url — нужен прямой публичный URL (для Яндекс Диска — "
                        "публичная ссылка или будущий media-proxy Botfleet)."
                    )
            else:
                would_attach_media = route.would_attach_media if route is not None else False
                if route is not None:
                    item_warnings.extend(route.media_warnings)

            if not live_implemented:
                item_warnings.append(
                    f"Live publishing for {platform} is not implemented yet "
                    "(только dry-run/preview)"
                )
            capabilities_read = self._capabilities_read(caps, live_implemented) if caps else None

            warnings.extend(item_warnings)
            items.append(
                PublicationPreviewItem(
                    platform=platform,
                    target_id=target_id,
                    text=publish_request.text,
                    hashtags=publish_request.hashtags,
                    media_asset_id=post.media_asset_id,
                    media_source=media_source,
                    preferred_media_path=publish_request.media_path,
                    media_kind=media_kind,
                    media_count=media_count,
                    media_asset_ids=media_asset_ids,
                    would_attach_media=would_attach_media,
                    would_prepare_media=would_prepare_media,
                    needs_public_image_url=needs_public_image_url,
                    media_warnings=item_warnings,
                    unsupported_media_reason=unsupported_media_reason,
                    upload_strategy=upload_strategy,
                    platform_capabilities=capabilities_read,
                    live_enabled=live_enabled,
                    would_send=live_enabled and bool(target_id) and live_implemented,
                    credentials_source=str(payload.get("credentials_source", "missing")),
                    token_present=bool(payload.get("token_present", False)),
                )
            )
        return PostPublishPreview(
            post_id=post_id, post_status=post.status, items=items, warnings=warnings
        )

    def list_platform_capabilities(self) -> list[PlatformCapabilitiesRead]:
        """Вернуть возможности всех платформ (для API/диагностики; без сети)."""
        available = set(self._registry.get_available_platforms())
        result: list[PlatformCapabilitiesRead] = []
        for platform, caps in platform_capabilities.get_platform_capabilities().items():
            if platform in available:
                live_implemented = bool(
                    getattr(self._registry.get_client(platform), "live_implemented", True)
                )
            else:
                live_implemented = platform not in platform_capabilities.LIVE_NOT_IMPLEMENTED
            result.append(self._capabilities_read(caps, live_implemented))
        return result

    @staticmethod
    def _preferred_media(db: Session, asset: MediaAsset) -> tuple[str | None, str, int | None]:
        """Вернуть (путь, источник, id_варианта): улучшенную копию, если одобрена.

        Берём самый свежий approved enhanced-вариант С готовым файлом — поэтому
        ``media_source='enhanced_variant'`` всегда сопровождается реальным путём.
        """
        variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(db, asset.id)
        if variant is not None:
            return variant.output_path, "enhanced_variant", variant.id
        return None, "original", None

    # --- Группа медиа (несколько вложений в одном посте) ---

    @staticmethod
    def _group_media_asset_ids(post: Post) -> list[int]:
        """Идентификаторы медиа группы из generation_notes (пустой список, если нет)."""
        raw = (post.generation_notes or {}).get("media_asset_ids")
        if not isinstance(raw, list):
            return []
        return [value for value in raw if isinstance(value, int)]

    def _build_media_items(self, db: Session, media_asset_ids: list[int]) -> list[dict[str, Any]]:
        """Собрать описания медиа группы (с учётом enhanced-копии) для загрузки."""
        items: list[dict[str, Any]] = []
        for media_id in media_asset_ids:
            asset = media_asset_repository.get_media_asset_by_id(db, media_id)
            if asset is None:
                continue
            media_path, media_source, _variant_id = self._preferred_media(db, asset)
            items.append(
                {
                    "id": asset.id,
                    "file_name": asset.file_name,
                    "yandex_disk_path": asset.yandex_disk_path,
                    "media_path": media_path,
                    "media_source": media_source,
                    "media_kind": _media_kind(media_path or asset.file_name),
                }
            )
        return items

    @staticmethod
    def _group_media_kind(media_items: list[dict[str, Any]]) -> str:
        """Общий тип группы: image / image_group / video / mixed / none."""
        kinds = [str(item.get("media_kind")) for item in media_items]
        images = kinds.count("image")
        videos = kinds.count("video")
        if images and videos:
            return "mixed"
        if images >= 2:
            return "image_group"
        if images == 1:
            return "image"
        if videos:
            return "video"
        return "none"

    # --- Мультиплатформенность (capability-слой) ---

    @staticmethod
    def _platform_text(post: Post, platform: str) -> str | None:
        """Текст под платформу: telegram/instagram — свои; vk/youtube/rutube — vk_text."""
        if platform == "telegram":
            return post.telegram_text
        if platform == "instagram":
            return post.instagram_text or post.vk_text
        return post.vk_text

    @staticmethod
    def _effective_media_items(payload: dict[str, object]) -> list[dict[str, object]]:
        """Медиа для capability-роутинга: группа media_items или одиночное медиа."""
        media_items = payload.get("media_items")
        if isinstance(media_items, list) and media_items:
            return [item for item in media_items if isinstance(item, dict)]
        media_kind = str(payload.get("media_kind", "none"))
        if media_kind in {"image", "video"}:
            return [{"media_kind": media_kind}]
        return []

    @staticmethod
    def _limit_warnings(
        route: platform_capabilities.MediaRoutingDecision | None, existing: list[str]
    ) -> list[str]:
        """Предупреждения об усечении по лимиту из capability-слоя (без дублей).

        Для VK/Telegram видео-предупреждения формируются отдельно (точные тексты),
        а из роутера добираем только про лимит фото, чтобы dry-run честно показывал
        усечение группы (например, 7 фото → первые 5).
        """
        if route is None:
            return []
        return [
            warning
            for warning in route.media_warnings
            if "лимит" in warning and warning not in existing
        ]

    @staticmethod
    def _capabilities_read(
        caps: PlatformCapabilities, live_implemented: bool
    ) -> PlatformCapabilitiesRead:
        """Собрать представление возможностей платформы для preview/API."""
        return PlatformCapabilitiesRead(
            platform=caps.platform,
            supports_text=caps.supports_text,
            supports_image=caps.supports_image,
            supports_image_group=caps.supports_image_group,
            supports_video=caps.supports_video,
            supports_video_group=caps.supports_video_group,
            max_images=caps.max_images,
            max_videos=caps.max_videos,
            max_text_length=caps.max_text_length,
            live_flag_name=caps.live_flag_name,
            live_implemented=live_implemented,
            notes=list(caps.notes),
        )

    def _resolve_preview_target(self, db: Session, post_id: int, platform: str) -> str | None:
        existing = post_publication_repository.get_publication_by_post_and_platform(
            db, post_id, platform
        )
        target_default = self._default_targets.get(platform)
        return (existing.target_id if existing is not None else None) or target_default

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
