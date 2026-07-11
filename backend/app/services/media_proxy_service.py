"""Media-proxy: временные публичные HTTPS-ссылки на медиа (для Instagram и др.).

Instagram Graph API публикует по публичному ``image_url``, а не по локальному файлу.
Botfleet выдаёт ссылку ``/media/public/{token}``:

- токен случайный (``secrets.token_urlsafe``), в БД хранится только ``sha256(token)``;
- ссылка привязана к project/media_asset, ограничена по времени, отзывается;
- HEIC/HEIF отдаётся как JPEG-конверсия;
- content-type ограничен allowlist, размер — лимитом; внутренний путь не раскрывается.

Реальная сеть используется только для скачивания публичного медиа Яндекс Диска (через
инъектируемый ``downloader``; в тестах — fake). Instagram media_publish НЕ вызывается.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.media_attachments import (
    HEIC_EXTENSIONS,
    content_type,
    extension,
    load_item_bytes,
    maybe_convert_heic,
)
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    post_repository,
    project_repository,
    public_media_link_repository,
)
from app.services.audit_log_service import (
    ACTION_MEDIA_PROXY_LINK_CREATED,
    ACTION_MEDIA_PROXY_LINK_REVOKED,
    AuditLogService,
)

if TYPE_CHECKING:
    from app.integrations.media_attachments import (
        SupportsImageConversion,
        SupportsPublicMediaDownload,
    )
    from app.models.public_media_link import PublicMediaLink

PURPOSES: tuple[str, ...] = ("instagram", "preview", "external_platform", "download", "other")


class MediaProxyError(Exception):
    """Ошибка media-proxy (нет актива, чужой проект, недопустимый тип) — API → 400."""


class MediaProxyNotAvailableError(MediaProxyError):
    """Ссылка недоступна: не найдена / отозвана / истекла / медиа недоступно (→ 404)."""


@dataclass(frozen=True)
class PublicMediaLinkResult:
    """Результат создания публичной ссылки (real url отдаётся один раз)."""

    id: int
    url: str
    url_masked: str
    token_prefix: str
    expires_at: str | None
    content_type: str | None
    file_name: str | None
    media_asset_id: int
    status: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedPublicMedia:
    """Разрешённое содержимое публичной ссылки (для отдачи в HTTP-ответе)."""

    content: bytes
    file_name: str
    content_type: str
    content_length: int
    link: Any


class MediaProxyService:
    """Создание/резолв/отзыв публичных медиа-ссылок (media-proxy)."""

    def __init__(
        self,
        settings: Settings | None = None,
        audit_service: AuditLogService | None = None,
        downloader: SupportsPublicMediaDownload | None = None,
        image_processor: SupportsImageConversion | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._audit = audit_service or AuditLogService(self._settings)
        self._downloader = downloader
        self._processor = image_processor

    # --- Помощники ---------------------------------------------------- #

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def build_public_url(self, token: str) -> str:
        """Собрать публичный URL ссылки из base URL и токена."""
        base = self._settings.media_proxy_public_base_url_effective
        return f"{base}/media/public/{token}"

    def mask_public_url(self, url: str) -> str:
        """Замаскировать токен в публичном URL (для показа в UI/логах)."""
        marker = "/media/public/"
        if marker in url:
            head, token = url.split(marker, 1)
            tail = token[:6]
            return f"{head}{marker}{tail}…••••"
        return url

    def _mask_from_prefix(self, token_prefix: str | None) -> str:
        base = self._settings.media_proxy_public_base_url_effective
        return f"{base}/media/public/{(token_prefix or '')}…••••"

    def _downloader_impl(self) -> SupportsPublicMediaDownload | None:
        if self._downloader is not None:
            return self._downloader
        from app.integrations.yandex_disk.client import YandexDiskPublicClient
        from app.services.media_download_service import MediaDownloadService

        self._downloader = MediaDownloadService(
            public_client=YandexDiskPublicClient(base_url=self._settings.yandex_disk_base_url),
            public_key=self._settings.yandex_disk_public_smm_url or None,
        )
        return self._downloader

    def _processor_impl(self) -> SupportsImageConversion | None:
        if self._processor is not None:
            return self._processor
        from app.services.image_enhancement_processor import ImageEnhancementProcessor

        self._processor = ImageEnhancementProcessor(
            output_format=self._settings.media_enhancement_output_format,
            jpeg_quality=self._settings.media_enhancement_jpeg_quality,
            max_image_mb=self._settings.media_enhancement_max_image_mb,
        )
        return self._processor

    @staticmethod
    def _effective_type_and_name(file_name: str) -> tuple[str, str]:
        """Определить итоговые content-type и имя (HEIC → jpg) без загрузки байтов."""
        if extension(file_name) in HEIC_EXTENSIONS:
            stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
            return "image/jpeg", f"{stem}.jpg"
        return content_type(file_name), file_name

    # --- Создание ссылок ---------------------------------------------- #

    def create_public_link(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        purpose: str = "instagram",
        ttl_seconds: int | None = None,
        current_user_id: int | None = None,
    ) -> PublicMediaLinkResult:
        """Создать временную публичную ссылку для медиа-актива проекта."""
        purpose = (purpose or "instagram").strip().lower()
        if purpose not in PURPOSES:
            raise MediaProxyError(f"Недопустимая цель ссылки: {purpose!r}")
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None:
            raise MediaProxyError(f"Медиа-актив #{media_asset_id} не найден")
        if asset.project_id != project_id:
            # Не раскрываем существование чужого актива.
            raise MediaProxyError("Медиа-актив не принадлежит проекту")

        project = project_repository.get_project_by_id(db, project_id)
        account_id = project.account_id if project is not None else None

        ttl = (
            ttl_seconds
            if ttl_seconds and ttl_seconds > 0
            else self._settings.media_proxy_default_ttl_seconds
        )
        ttl = min(int(ttl), self._settings.media_proxy_max_ttl_seconds)
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)

        variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(db, asset.id)
        base_name = (
            Path(variant.output_path).name
            if variant is not None and variant.output_path
            else asset.file_name
        )
        ctype, out_name = self._effective_type_and_name(base_name)

        token = secrets.token_urlsafe(max(16, self._settings.media_proxy_token_bytes))
        token_prefix = token[:8]
        link = public_media_link_repository.create_link(
            db,
            account_id=account_id,
            project_id=project_id,
            media_asset_id=asset.id,
            media_asset_variant_id=variant.id if variant is not None else None,
            token_hash=self._hash_token(token),
            token_prefix=token_prefix,
            purpose=purpose,
            status="active",
            content_type=ctype,
            file_name=out_name,
            expires_at=expires_at,
            created_by_user_id=current_user_id,
            link_metadata={"source": "media_proxy"},
        )
        self._audit.record(
            db,
            ACTION_MEDIA_PROXY_LINK_CREATED,
            account_id=account_id,
            user_id=current_user_id,
            project_id=project_id,
            entity_type="public_media_link",
            entity_id=link.id,
            metadata={
                "purpose": purpose,
                "media_asset_id": asset.id,
                "expires_at": expires_at.isoformat(),
            },
        )
        url = self.build_public_url(token)
        return PublicMediaLinkResult(
            id=link.id,
            url=url,
            url_masked=self.mask_public_url(url),
            token_prefix=token_prefix,
            expires_at=expires_at.isoformat(),
            content_type=ctype,
            file_name=out_name,
            media_asset_id=asset.id,
            status=link.status,
            warnings=self.validate_public_base_url().get("warnings", []),
        )

    def create_public_links_for_post(
        self,
        db: Session,
        post_id: int,
        platform: str = "instagram",
        purpose: str = "instagram",
        max_items: int = 10,
        ttl_seconds: int | None = None,
        current_user_id: int | None = None,
    ) -> list[PublicMediaLinkResult]:
        """Создать публичные ссылки для медиа поста (media_asset_ids)."""
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise MediaProxyError(f"Пост #{post_id} не найден")
        notes = post.generation_notes or {}
        ids = notes.get("media_asset_ids")
        asset_ids: list[int] = (
            [v for v in ids if isinstance(v, int)] if isinstance(ids, list) else []
        )
        if not asset_ids and post.media_asset_id is not None:
            asset_ids = [post.media_asset_id]
        results: list[PublicMediaLinkResult] = []
        for asset_id in asset_ids[: max(0, max_items)]:
            results.append(
                self.create_public_link(
                    db, post.project_id, asset_id, purpose, ttl_seconds, current_user_id
                )
            )
        return results

    # --- Резолв (публичный GET) --------------------------------------- #

    def resolve_token(self, db: Session, token: str) -> ResolvedPublicMedia:
        """Разрешить токен → содержимое медиа (или MediaProxyNotAvailableError → 404).

        Внутренние пути файлов НЕ раскрываются в ошибках.
        """
        if not token:
            raise MediaProxyNotAvailableError("Ссылка не найдена")
        link = public_media_link_repository.get_by_token_hash(db, self._hash_token(token))
        if link is None or link.status == "revoked":
            raise MediaProxyNotAvailableError("Ссылка не найдена или отозвана")
        now = datetime.now(UTC)
        if link.expires_at is not None and _aware(link.expires_at) < now:
            if link.status == "active":
                public_media_link_repository.mark_expired(db, link)
            raise MediaProxyNotAvailableError("Срок действия ссылки истёк")
        if link.status != "active":
            raise MediaProxyNotAvailableError("Ссылка недоступна")

        asset = media_asset_repository.get_media_asset_by_id(db, link.media_asset_id)
        if asset is None:
            raise MediaProxyNotAvailableError("Медиа недоступно")

        media_path: str | None = None
        if link.media_asset_variant_id is not None:
            variant = media_asset_variant_repository.get_variant_by_id(
                db, link.media_asset_variant_id
            )
            if variant is not None and variant.output_path and Path(variant.output_path).is_file():
                media_path = variant.output_path

        item = {
            "media_path": media_path,
            "yandex_disk_path": asset.yandex_disk_path,
            "file_name": asset.file_name,
        }
        content, file_name = load_item_bytes(item, self._downloader_impl())
        if content is None:
            raise MediaProxyNotAvailableError("Медиа недоступно")
        content, file_name, ctype = maybe_convert_heic(content, file_name, self._processor_impl())

        allowed = self._settings.media_proxy_allowed_content_types_list
        if allowed and ctype.lower() not in allowed:
            raise MediaProxyNotAvailableError("Тип содержимого не поддерживается")
        if len(content) > self._settings.media_proxy_max_bytes:
            raise MediaProxyNotAvailableError("Файл слишком большой")

        public_media_link_repository.increment_access(db, link, now)
        return ResolvedPublicMedia(
            content=content,
            file_name=file_name,
            content_type=ctype,
            content_length=len(content),
            link=link,
        )

    # --- Отзыв / список ------------------------------------------------ #

    def revoke_link(
        self, db: Session, project_id: int, link_id: int, current_user_id: int | None = None
    ) -> bool:
        """Отозвать ссылку проекта. Чужая ссылка не отзывается (возврат False)."""
        link = public_media_link_repository.get_by_id(db, link_id)
        if link is None or link.project_id != project_id:
            return False
        if link.status == "active":
            public_media_link_repository.revoke_link(db, link, datetime.now(UTC))
        self._audit.record(
            db,
            ACTION_MEDIA_PROXY_LINK_REVOKED,
            account_id=link.account_id,
            user_id=current_user_id,
            project_id=project_id,
            entity_type="public_media_link",
            entity_id=link.id,
            metadata={"purpose": link.purpose, "media_asset_id": link.media_asset_id},
        )
        return True

    def mask_link(self, link: PublicMediaLink) -> dict[str, Any]:
        """Безопасное представление ссылки (без raw-токена)."""
        return {
            "id": link.id,
            "project_id": link.project_id,
            "media_asset_id": link.media_asset_id,
            "purpose": link.purpose,
            "status": link.status,
            "content_type": link.content_type,
            "file_name": link.file_name,
            "token_prefix": link.token_prefix,
            "url_masked": self._mask_from_prefix(link.token_prefix),
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
            "revoked_at": link.revoked_at.isoformat() if link.revoked_at else None,
            "last_accessed_at": (
                link.last_accessed_at.isoformat() if link.last_accessed_at else None
            ),
            "hit_count": link.hit_count,
            "created_at": link.created_at.isoformat() if link.created_at else None,
        }

    def list_project_links(
        self, db: Session, project_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Ссылки проекта (маскированные, без токенов)."""
        links = public_media_link_repository.list_for_project(db, project_id, limit=limit)
        return [self.mask_link(link) for link in links]

    # --- Валидация base URL ------------------------------------------- #

    def validate_public_base_url(self) -> dict[str, Any]:
        """Проверить готовность публичного base URL (warnings/errors, без секретов)."""
        s = self._settings
        base = s.media_proxy_public_base_url_effective
        warnings: list[str] = []
        errors: list[str] = []
        if not s.media_proxy_enabled:
            warnings.append("MEDIA_PROXY_ENABLED=false — публичные ссылки выключены.")
        if not base:
            errors.append(
                "Не задан публичный base URL (MEDIA_PROXY_PUBLIC_BASE_URL/PUBLIC_APP_URL)."
            )
        low = base.lower()
        if (
            s.is_production
            and s.media_proxy_require_https_in_production
            and not s.media_proxy_https_ready
        ):
            errors.append("В production нужен публичный HTTPS-домен (не localhost).")
        if not s.is_production and ("127.0.0.1" in low or "localhost" in low):
            warnings.append(
                "Локальный base URL (localhost/127.0.0.1) недоступен внешним платформам "
                "(Instagram/Meta) — нужен публичный HTTPS-домен."
            )
        elif base and not low.startswith("https://"):
            warnings.append("Base URL не HTTPS — внешние платформы требуют HTTPS.")
        return {
            "enabled": s.media_proxy_enabled,
            "base_url": base,
            "https_ready": s.media_proxy_https_ready,
            "default_ttl_seconds": s.media_proxy_default_ttl_seconds,
            "max_bytes": s.media_proxy_max_bytes,
            "allowed_content_types": s.media_proxy_allowed_content_types_list,
            "warnings": warnings,
            "errors": errors,
        }


def _aware(value: datetime) -> datetime:
    """Привести datetime к timezone-aware UTC (SQLite может вернуть naive)."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def get_media_proxy_service() -> MediaProxyService:
    """DI-фабрика media-proxy сервиса."""
    return MediaProxyService()
