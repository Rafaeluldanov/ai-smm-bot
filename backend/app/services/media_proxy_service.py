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

import contextlib
import hashlib
import os
import secrets
import time
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
    media_proxy_repository,
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

# Трансформация по площадке (v0.6.2). Оригинал — только если MEDIA_PROXY_ALLOW_ORIGINAL.
_PLATFORM_TRANSFORM: dict[str, str] = {
    "instagram": "width_1080",
    "vk": "original",
    "telegram": "original",
}
_TRANSFORM_TOKEN_TYPE: dict[str, str] = {
    "original": "original",
    "social_preview": "preview",
    "width_640": "thumbnail",
    "width_1080": "image",
    "square": "image",
}


class MediaProxyError(Exception):
    """Ошибка media-proxy (нет актива, чужой проект, недопустимый тип) — API → 400."""


class MediaProxyNotAvailableError(MediaProxyError):
    """Ссылка недоступна: не найдена / отозвана / истекла / лимит / медиа недоступно.

    ``status`` — HTTP-код (404/403/410), ``blocker`` — код причины (см. MEDIA_PROXY_BLOCKERS).
    """

    def __init__(self, message: str, status: int = 404, blocker: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.blocker = blocker


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
    transform: str = "original"
    token_type: str = "image"
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

    @staticmethod
    def _normalize_transform(transform: str | None) -> str:
        from app.models.public_media_link import MEDIA_PROXY_TRANSFORMS

        key = (transform or "original").strip().lower()
        return key if key in MEDIA_PROXY_TRANSFORMS else "original"

    def _apply_transform(
        self, content: bytes, file_name: str, ctype: str, transform: str
    ) -> tuple[bytes, str, str]:
        """Применить трансформацию доставки на лету (с файловым кешем). «original» — без ресайза."""
        transform = self._normalize_transform(transform)
        if transform == "original" or not self._settings.media_proxy_resize_enabled_effective:
            return content, file_name, ctype
        if not ctype.lower().startswith("image/"):
            return content, file_name, ctype
        processor = self._processor_impl()
        if processor is None:
            return content, file_name, ctype
        cached = self._cache_get(content, transform)
        if cached is not None:
            content = cached
        else:
            try:
                content, _w, _h = processor.transform_bytes(content, transform)
            except Exception:  # noqa: BLE001 — при сбое ресайза отдаём как есть (best-effort)
                return content, file_name, ctype
            self._cache_put(content, transform, cached_from=content)
        out_format = (self._settings.media_enhancement_output_format or "jpg").lower()
        out_ctype = "image/webp" if out_format == "webp" else "image/jpeg"
        stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        ext = "webp" if out_format == "webp" else "jpg"
        return content, f"{stem}.{ext}", out_ctype

    # --- Файловый кеш трансформаций (best-effort) --------------------- #

    def _cache_path(self, content: bytes, transform: str) -> Path | None:
        if not self._settings.media_proxy_cache_enabled:
            return None
        key = hashlib.sha256(content).hexdigest()
        safe_transform = "".join(c for c in transform if c.isalnum() or c == "_")
        return Path(self._settings.media_proxy_cache_dir) / f"{key}.{safe_transform}.bin"

    def _cache_get(self, content: bytes, transform: str) -> bytes | None:
        path = self._cache_path(content, transform)
        if path is None or not path.is_file():
            return None
        ttl = self._settings.media_proxy_cache_seconds_safe
        try:
            if ttl and (time.time() - path.stat().st_mtime) > ttl:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def _cache_put(self, transformed: bytes, transform: str, *, cached_from: bytes) -> None:
        path = self._cache_path(cached_from, transform)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            tmp.write_bytes(transformed)
            tmp.replace(path)
        except OSError:
            return

    def _log_access(
        self,
        db: Session,
        link_id: int | None,
        media_asset_id: int | None,
        *,
        status: int,
        request_ip: str | None,
        user_agent: str | None,
        transform: str | None,
        size: int | None,
        ctype: str | None,
    ) -> None:
        """Записать обращение (только хеши IP/UA; без секретов). Ошибки не роняют отдачу."""
        try:
            media_proxy_repository.create_access_log(
                db,
                public_media_link_id=link_id,
                media_asset_id=media_asset_id,
                status=status,
                request_ip_hash=self._hash_optional(request_ip),
                user_agent_hash=self._hash_optional(user_agent),
                response_type=ctype,
                response_size=size,
                transform=transform,
            )
        except Exception:  # noqa: BLE001 — журнал не критичен для отдачи
            with contextlib.suppress(Exception):
                db.rollback()

    @staticmethod
    def _hash_optional(value: str | None) -> str | None:
        if not value:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    # --- Создание ссылок ---------------------------------------------- #

    def create_public_link(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        purpose: str = "instagram",
        ttl_seconds: int | None = None,
        current_user_id: int | None = None,
        transform: str = "original",
        token_type: str | None = None,
        max_requests: int | None = None,
    ) -> PublicMediaLinkResult:
        """Создать временную публичную ссылку для медиа-актива проекта."""
        purpose = (purpose or "instagram").strip().lower()
        if purpose not in PURPOSES:
            raise MediaProxyError(f"Недопустимая цель ссылки: {purpose!r}")
        transform = self._normalize_transform(transform)
        # По умолчанию — «image» (legacy-ссылки отдаются как раньше). Явный «original»-тип
        # (гейтится ALLOW_ORIGINAL) выставляют только методы доставки create_media_url/social.
        token_type = token_type or "image"
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
            token_type=token_type,
            transform=transform,
            max_requests=max_requests,
            status="active",
            content_type=ctype,
            file_name=out_name,
            expires_at=expires_at,
            created_by_user_id=current_user_id,
            link_metadata={"source": "media_proxy"},
        )
        media_asset_repository.mark_proxy_generated(db, asset, datetime.now(UTC))
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
            transform=transform,
            token_type=token_type,
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

        # Лимит запросов на токен (0 = без лимита).
        limit = (
            link.max_requests if link.max_requests else self._settings.media_proxy_max_requests_safe
        )
        if limit and int(link.hit_count) >= int(limit):
            raise MediaProxyNotAvailableError(
                "Исчерпан лимит запросов ссылки", status=403, blocker="request_limit_reached"
            )
        # Отдача оригинала может быть выключена (по умолчанию — выключена).
        if (
            link.token_type == "original"
            and not self._settings.media_proxy_allow_original_effective
        ):
            raise MediaProxyNotAvailableError(
                "Отдача оригинала выключена", status=403, blocker="original_not_allowed"
            )

        asset = media_asset_repository.get_media_asset_by_id(db, link.media_asset_id)
        if asset is None:
            raise MediaProxyNotAvailableError(
                "Медиа недоступно", status=404, blocker="missing_asset"
            )

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
            raise MediaProxyNotAvailableError(
                "Медиа недоступно", status=404, blocker="file_not_found"
            )
        content, file_name, ctype = maybe_convert_heic(content, file_name, self._processor_impl())

        # Трансформация доставки (ресайз/квадрат) на лету, если включена и это не «original».
        content, file_name, ctype = self._apply_transform(content, file_name, ctype, link.transform)

        allowed = self._settings.media_proxy_allowed_content_types_list
        if allowed and ctype.lower() not in allowed:
            raise MediaProxyNotAvailableError(
                "Тип содержимого не поддерживается", status=404, blocker="unsupported_format"
            )
        if len(content) > self._settings.media_proxy_max_bytes:
            raise MediaProxyNotAvailableError("Файл слишком большой", status=404)

        public_media_link_repository.increment_access(db, link, now)
        return ResolvedPublicMedia(
            content=content,
            file_name=file_name,
            content_type=ctype,
            content_length=len(content),
            link=link,
        )

    def get_media_response(
        self,
        db: Session,
        token: str,
        request_ip: str | None = None,
        user_agent: str | None = None,
    ) -> ResolvedPublicMedia:
        """Публичная отдача с журналированием обращения (успех/ошибка). Транзформа применяется.

        Пишет ``MediaProxyAccessLog`` (только хеши IP/UA, без секретов) и re-raise при ошибке.
        """
        try:
            resolved = self.resolve_token(db, token)
        except MediaProxyNotAvailableError as exc:
            self._log_access(
                db,
                None,
                None,
                status=getattr(exc, "status", 404),
                request_ip=request_ip,
                user_agent=user_agent,
                transform=None,
                size=None,
                ctype=None,
            )
            raise
        self._log_access(
            db,
            resolved.link.id,
            resolved.link.media_asset_id,
            status=200,
            request_ip=request_ip,
            user_agent=user_agent,
            transform=resolved.link.transform,
            size=resolved.content_length,
            ctype=resolved.content_type,
        )
        return resolved

    # --- Delivery layer (v0.6.2): create_media_url / social / preview ------- #

    def create_media_url(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        transform: str = "original",
        ttl_seconds: int | None = None,
        max_requests: int | None = None,
        purpose: str = "external_platform",
        current_user_id: int | None = None,
    ) -> PublicMediaLinkResult:
        """Создать подписанный публичный URL доставки для медиа-актива с трансформацией."""
        transform = self._normalize_transform(transform)
        return self.create_public_link(
            db,
            project_id,
            media_asset_id,
            purpose=purpose,
            ttl_seconds=ttl_seconds,
            current_user_id=current_user_id,
            transform=transform,
            token_type=_TRANSFORM_TOKEN_TYPE.get(transform, "image"),
            max_requests=max_requests,
        )

    def build_social_media_url(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        platform: str,
        ttl_seconds: int | None = None,
        current_user_id: int | None = None,
    ) -> PublicMediaLinkResult:
        """Создать URL доставки, оптимальный для площадки (instagram=1080, vk/telegram=original)."""
        platform = (platform or "").strip().lower()
        transform = _PLATFORM_TRANSFORM.get(platform, "width_1080")
        # Если оригинал выключен — понижаем до 1080, чтобы доставка всё равно работала.
        if transform == "original" and not self._settings.media_proxy_allow_original_effective:
            transform = "width_1080"
        return self.create_public_link(
            db,
            project_id,
            media_asset_id,
            purpose="external_platform",
            ttl_seconds=ttl_seconds,
            current_user_id=current_user_id,
            transform=transform,
            token_type=_TRANSFORM_TOKEN_TYPE.get(transform, "image"),
        )

    def generate_preview_url(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        ttl_seconds: int | None = None,
        current_user_id: int | None = None,
    ) -> PublicMediaLinkResult:
        """Создать URL превью (social_preview) для UI."""
        return self.create_public_link(
            db,
            project_id,
            media_asset_id,
            purpose="preview",
            ttl_seconds=ttl_seconds,
            current_user_id=current_user_id,
            transform="social_preview",
            token_type="preview",
        )

    def build_platform_urls(
        self, db: Session, project_id: int, media_asset_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать набор ссылок (preview/instagram/vk/telegram[/original]) для UI/API."""
        out: dict[str, Any] = {"media_asset_id": media_asset_id, "urls": {}}
        variants: list[tuple[str, str]] = [
            ("preview", "social_preview"),
            ("instagram", _PLATFORM_TRANSFORM["instagram"]),
            ("vk", _PLATFORM_TRANSFORM["vk"]),
            ("telegram", _PLATFORM_TRANSFORM["telegram"]),
        ]
        if self._settings.media_proxy_allow_original_effective:
            variants.append(("original", "original"))
        for key, transform in variants:
            eff = transform
            if eff == "original" and not self._settings.media_proxy_allow_original_effective:
                eff = "width_1080"
            result = self.create_public_link(
                db,
                project_id,
                media_asset_id,
                purpose="preview" if key == "preview" else "external_platform",
                current_user_id=current_user_id,
                transform=eff,
                token_type="preview"
                if key == "preview"
                else _TRANSFORM_TOKEN_TYPE.get(eff, "image"),
            )
            out["urls"][key] = {
                "url": result.url,
                "url_masked": result.url_masked,
                "transform": result.transform,
                "expires_at": result.expires_at,
                "link_id": result.id,
            }
        return out

    def validate_token(self, db: Session, token: str) -> dict[str, Any]:
        """Проверить токен (hash/TTL/active/лимит) БЕЗ отдачи содержимого."""
        if not token:
            return {"valid": False, "blocker": "invalid_signature", "status": 404}
        link = public_media_link_repository.get_by_token_hash(db, self._hash_token(token))
        if link is None:
            return {"valid": False, "blocker": "invalid_signature", "status": 404}
        if link.status == "revoked":
            return {"valid": False, "blocker": "invalid_signature", "status": 403}
        now = datetime.now(UTC)
        if link.expires_at is not None and _aware(link.expires_at) < now:
            return {"valid": False, "blocker": "expired_token", "status": 410}
        if link.status != "active":
            return {"valid": False, "blocker": "expired_token", "status": 410}
        limit = (
            link.max_requests if link.max_requests else self._settings.media_proxy_max_requests_safe
        )
        if limit and int(link.hit_count) >= int(limit):
            return {"valid": False, "blocker": "request_limit_reached", "status": 403}
        if (
            link.token_type == "original"
            and not self._settings.media_proxy_allow_original_effective
        ):
            return {"valid": False, "blocker": "original_not_allowed", "status": 403}
        return {
            "valid": True,
            "status": 200,
            "transform": link.transform,
            "token_type": link.token_type,
            "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        }

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

    @property
    def settings(self) -> Settings:
        """Доступ к настройкам (для API-слоя: cache-заголовки и т. п.)."""
        return self._settings

    def mask_link(self, link: PublicMediaLink) -> dict[str, Any]:
        """Безопасное представление ссылки (без raw-токена)."""
        return {
            "id": link.id,
            "project_id": link.project_id,
            "media_asset_id": link.media_asset_id,
            "purpose": link.purpose,
            "token_type": link.token_type,
            "transform": link.transform,
            "max_requests": link.max_requests,
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

    def list_asset_delivery(
        self, db: Session, project_id: int, media_asset_id: int
    ) -> dict[str, Any]:
        """Существующие токены доставки актива (маскированные) + последние обращения."""
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise MediaProxyError("Медиа-актив не найден")
        tokens = media_proxy_repository.list_asset_tokens(db, media_asset_id)
        logs = media_proxy_repository.list_access_logs(db, media_asset_id, limit=20)
        return {
            "project_id": project_id,
            "media_asset_id": media_asset_id,
            "proxy_ready": bool(asset.proxy_ready),
            "last_proxy_generated_at": (
                asset.last_proxy_generated_at.isoformat() if asset.last_proxy_generated_at else None
            ),
            "tokens": [self.mask_link(t) for t in tokens],
            "recent_access": [media_proxy_repository.public_access_log_view(log) for log in logs],
        }

    def disable_token_by_id(
        self, db: Session, token_id: int, current_user_id: int | None = None
    ) -> bool:
        """Отключить токен по id (доступ уже проверен гардом). Возврат True, если отключён."""
        token = public_media_link_repository.get_by_id(db, token_id)
        if token is None:
            return False
        if token.status == "active":
            public_media_link_repository.revoke_link(db, token, datetime.now(UTC))
        self._audit.record(
            db,
            ACTION_MEDIA_PROXY_LINK_REVOKED,
            account_id=token.account_id,
            user_id=current_user_id,
            project_id=token.project_id,
            entity_type="public_media_link",
            entity_id=token.id,
            metadata={"purpose": token.purpose, "media_asset_id": token.media_asset_id},
        )
        return True

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
