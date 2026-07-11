"""Self-service подключения платформ: клиент заполняет API/ID в UI, без .env.

Хранит подключения в ``CrmSmmResource`` (одна запись на project+platform_key). Секреты
(токен площадки → ``api_key_encrypted``, app_secret → ``app_secret_encrypted``) шифруются
через :mod:`app.services.crm_secret_service` и НИКОГДА не возвращаются наружу — только
маска и факт наличия. Все действия пишутся в аудит автоматически.

Публикация проекта резолвит креды в порядке: подключение проекта → env-fallback (только
local) → «не подключено». Токен другого проекта использовать нельзя (tenant-изоляция по
project_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.crm_bot_smm import CrmSmmResource
from app.models.user import User
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import project_repository
from app.services import crm_secret_service
from app.services.audit_log_service import (
    ACTION_CONNECTION_CHECK_FAILED,
    ACTION_CONNECTION_CHECKED,
    ACTION_CONNECTION_CREATED,
    ACTION_CONNECTION_DELETED,
    ACTION_CONNECTION_SECRET_UPDATED,
    ACTION_CONNECTION_UPDATED,
    AuditLogService,
)
from app.services.platform_connection_check_service import (
    ConnectionCheckInput,
    PlatformCheckResult,
    PlatformConnectionCheckService,
)
from app.services.platform_connection_schema_service import PlatformConnectionSchemaService

# Платформы, для которых поле url хранится ещё и как публичная ссылка на медиа.
_MEDIA_URL_PLATFORMS = {"yandex_disk", "google_drive"}
# Соответствие платформы → (env-токен, env-target) для fallback (только local).
_ENV_FALLBACK = {
    "telegram": ("telegram_bot_token", "telegram_default_channel_id"),
    "vk": ("vk_access_token", "vk_default_group_id"),
    "instagram": ("instagram_access_token", "instagram_business_account_id"),
}


class PlatformConnectionError(Exception):
    """Ошибка подключения платформы (нет проекта, неизвестная платформа) — API → 400/404."""


class PlatformCredentialsMissingError(PlatformConnectionError):
    """Площадка не подключена в проекте и нет env-fallback — публикация невозможна."""


@dataclass(frozen=True)
class PublishCredentials:
    """Разрешённые креды публикации (токен — только для внутреннего использования)."""

    platform: str
    source: str  # project_connection | env_fallback | missing
    token_present: bool
    external_id: str | None
    message: str
    _token: str | None = None

    @property
    def token(self) -> str | None:
        """Токен для запроса к платформе (НИКОГДА не сериализуется наружу)."""
        return self._token

    @property
    def ok(self) -> bool:
        return self.source != "missing"

    def as_public_dict(self) -> dict[str, Any]:
        """Безопасное представление (без токена)."""
        return {
            "platform": self.platform,
            "credentials_source": self.source,
            "token_present": self.token_present,
            "external_id": self.external_id,
            "message": self.message,
        }


class PlatformConnectionService:
    """CRUD подключений платформ, проверка и резолв кредов публикации."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        check_service: PlatformConnectionCheckService | None = None,
        schema_service: PlatformConnectionSchemaService | None = None,
    ) -> None:
        self._audit = audit_service or AuditLogService()
        self._checks = check_service or PlatformConnectionCheckService()
        self._schemas = schema_service or PlatformConnectionSchemaService()

    # --- Конфигурация проекта (контейнер ресурсов) --- #

    def _get_or_create_config_id(self, db: Session, project_id: int) -> int:
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is not None:
            return config.id
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise PlatformConnectionError(f"Проект id={project_id} не найден")
        from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate

        config = crm_repo.create_config(
            db,
            CrmBotProjectConfigCreate(
                project_id=project_id,
                display_name=project.name or f"Проект {project_id}",
                status="active",
            ),
        )
        return config.id

    # --- Маскирование --- #

    @staticmethod
    def mask_connection(resource: CrmSmmResource) -> dict[str, Any]:
        """Безопасное представление подключения (без секретов — только маски/факты)."""
        return {
            "id": resource.id,
            "platform_key": resource.resource_type,
            "title": resource.title,
            "external_id": resource.external_id,
            "url": resource.url,
            "public_media_url": resource.yandex_public_url,
            "root_folder": resource.yandex_root_folder,
            "tags": list(resource.tags or []),
            "app_id": resource.app_id,
            "api_key_present": bool(resource.api_key_masked or resource.api_key_encrypted),
            "api_key_masked": resource.api_key_masked,
            "app_secret_present": bool(resource.app_secret_masked or resource.app_secret_encrypted),
            "app_secret_masked": resource.app_secret_masked,
            "live_enabled": resource.live_enabled,
            "status": resource.status,
            "is_active": resource.is_active,
            "last_check_at": resource.last_check_at.isoformat() if resource.last_check_at else None,
            "last_check_status": resource.last_check_status,
            "last_check_message": resource.last_check_message,
            "redirect_uri": (resource.resource_metadata or {}).get("redirect_uri"),
            "connected": bool(
                resource.is_active
                and (resource.api_key_masked or resource.external_id or resource.url)
            ),
        }

    # --- Чтение --- #

    def list_connections(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Все подключения проекта (маскированные, без секретов)."""
        resources = crm_repo.list_resources_by_project(db, project_id)
        return [self.mask_connection(r) for r in resources if r.is_active]

    def get_connection(
        self, db: Session, project_id: int, platform_key: str
    ) -> dict[str, Any] | None:
        """Одно подключение платформы (маскированное) или None."""
        resource = crm_repo.get_active_resource_by_project_platform(db, project_id, platform_key)
        return self.mask_connection(resource) if resource is not None else None

    def get_schema(self, platform_key: str) -> dict[str, Any]:
        """Схема формы подключения платформы (поля/шаги/предупреждения)."""
        return self._schemas.get_connection_schema(platform_key).as_dict()

    # --- Запись --- #

    def upsert_connection(
        self,
        db: Session,
        project_id: int,
        platform_key: str,
        payload: dict[str, Any],
        current_user: User | None = None,
    ) -> dict[str, Any]:
        """Создать/обновить подключение платформы. Секреты write-only (пустой → без изменений)."""
        platform_key = (platform_key or "").strip().lower()
        config_id = self._get_or_create_config_id(db, project_id)
        existing = crm_repo.get_active_resource_by_project_platform(db, project_id, platform_key)

        api_key = (payload.get("api_key") or "").strip()
        app_secret = (payload.get("app_secret") or "").strip()
        title = (payload.get("title") or "").strip() or self._schemas.get_connection_schema(
            platform_key
        ).title
        tags = payload.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        url = (payload.get("url") or "").strip() or None

        fields: dict[str, Any] = {
            "resource_type": platform_key,
            "title": title,
            "external_id": (payload.get("external_id") or "").strip() or None,
            "url": url,
            "app_id": (payload.get("app_id") or "").strip() or None,
            "tags": tags,
            # live всегда выключен из UI (защита от случайной публикации).
            "live_enabled": False,
        }
        if platform_key in _MEDIA_URL_PLATFORMS:
            fields["yandex_public_url"] = url
            fields["yandex_root_folder"] = (payload.get("root_folder") or "").strip() or None

        # Несекретные доп. параметры → resource_metadata.
        metadata = dict((existing.resource_metadata if existing else None) or {})
        for meta_key in ("redirect_uri", "default_cta"):
            value = (payload.get(meta_key) or "").strip()
            if value:
                metadata[meta_key] = value
        fields["resource_metadata"] = metadata

        secret_changed = False
        if api_key:
            fields["api_key_encrypted"] = crm_secret_service.encrypt_secret(api_key)
            fields["api_key_masked"] = crm_secret_service.mask_secret(api_key)
            secret_changed = True
        if app_secret:
            fields["app_secret_encrypted"] = crm_secret_service.encrypt_secret(app_secret)
            fields["app_secret_masked"] = crm_secret_service.mask_secret(app_secret)
            secret_changed = True

        if existing is None:
            fields["project_id"] = project_id
            fields["config_id"] = config_id
            fields["status"] = "draft"
            fields["is_active"] = True
            resource = crm_repo.create_resource_fields(db, fields)
            action = ACTION_CONNECTION_CREATED
        else:
            resource = crm_repo.update_resource_fields(db, existing, fields)
            action = ACTION_CONNECTION_UPDATED

        user_id = current_user.id if current_user is not None else None
        self._audit.record(
            db,
            action,
            account_id=None,
            user_id=user_id,
            project_id=project_id,
            entity_type="platform_connection",
            entity_id=resource.id,
            metadata={"platform": platform_key, "secret_changed": secret_changed},
        )
        if secret_changed:
            self._audit.record(
                db,
                ACTION_CONNECTION_SECRET_UPDATED,
                user_id=user_id,
                project_id=project_id,
                entity_type="platform_connection",
                entity_id=resource.id,
                metadata={"platform": platform_key},
            )
        return self.mask_connection(resource)

    def delete_connection(
        self, db: Session, project_id: int, platform_key: str, current_user: User | None = None
    ) -> bool:
        """Отключить платформу (soft delete: is_active=False). Секрет не раскрывается."""
        resource = crm_repo.get_active_resource_by_project_platform(db, project_id, platform_key)
        if resource is None:
            return False
        crm_repo.update_resource_fields(db, resource, {"is_active": False, "status": "draft"})
        self._audit.record(
            db,
            ACTION_CONNECTION_DELETED,
            user_id=current_user.id if current_user is not None else None,
            project_id=project_id,
            entity_type="platform_connection",
            entity_id=resource.id,
            metadata={"platform": platform_key},
        )
        return True

    # --- Проверка --- #

    def check_connection(
        self, db: Session, project_id: int, platform_key: str, http_client: Any = None
    ) -> dict[str, Any]:
        """Безопасно проверить подключение (read-only), записать результат и аудит."""
        platform_key = (platform_key or "").strip().lower()
        resource = crm_repo.get_active_resource_by_project_platform(db, project_id, platform_key)
        from app.services.platform_catalog_service import PlatformCatalogService

        item = PlatformCatalogService().get(platform_key)
        planned = bool(item is not None and item.is_planned)

        token = None
        if resource is not None and resource.api_key_encrypted:
            token = crm_secret_service.decrypt_secret(resource.api_key_encrypted)
        data = ConnectionCheckInput(
            platform_key=platform_key,
            token=token,
            external_id=resource.external_id if resource else None,
            url=(resource.yandex_public_url or resource.url) if resource else None,
            root_folder=resource.yandex_root_folder if resource else None,
            app_id=resource.app_id if resource else None,
        )
        result: PlatformCheckResult = self._checks.check(
            data, http_client=http_client, planned=planned
        )

        if resource is not None:
            new_status = (
                "connected"
                if result.status == "ok"
                else ("error" if result.status == "error" else "draft")
            )
            crm_repo.update_resource_fields(
                db,
                resource,
                {
                    "status": new_status,
                    "last_check_at": datetime.now(UTC),
                    "last_check_status": result.status,
                    "last_check_message": result.message[:1000],
                },
            )
        action = ACTION_CONNECTION_CHECKED if result.ok else ACTION_CONNECTION_CHECK_FAILED
        self._audit.record(
            db,
            action,
            project_id=project_id,
            entity_type="platform_connection",
            entity_id=resource.id if resource else None,
            metadata={"platform": platform_key, "status": result.status},
        )
        return result.as_dict()

    # --- Резолв кредов публикации --- #

    def resolve_publish_credentials(
        self, db: Session, project_id: int, platform_key: str
    ) -> PublishCredentials:
        """Найти креды публикации: подключение проекта → env-fallback (local) → missing.

        Токен другого проекта недоступен (поиск строго по project_id). Токен наружу не
        отдаётся: в ответе только источник, факт наличия и external_id.
        """
        platform_key = (platform_key or "").strip().lower()
        resource = crm_repo.get_active_resource_by_project_platform(db, project_id, platform_key)
        if resource is not None and resource.api_key_encrypted:
            token = crm_secret_service.decrypt_secret(resource.api_key_encrypted)
            return PublishCredentials(
                platform=platform_key,
                source="project_connection",
                token_present=True,
                external_id=resource.external_id,
                message="Используются креды подключения проекта.",
                _token=token,
            )

        settings = get_settings()
        env_map = _ENV_FALLBACK.get(platform_key)
        if env_map is not None and settings.is_local:
            token = str(getattr(settings, env_map[0], "") or "")
            target = str(getattr(settings, env_map[1], "") or "") or (
                resource.external_id if resource else None
            )
            if token:
                return PublishCredentials(
                    platform=platform_key,
                    source="env_fallback",
                    token_present=True,
                    external_id=target or None,
                    message="Используется env-fallback (только для local-совместимости).",
                    _token=token,
                )
        return PublishCredentials(
            platform=platform_key,
            source="missing",
            token_present=False,
            external_id=resource.external_id if resource else None,
            message=("Платформа не подключена в проекте. Откройте платформу и заполните API/ID."),
        )

    def require_publish_credentials(
        self, db: Session, project_id: int, platform_key: str
    ) -> PublishCredentials:
        """Как resolve_publish_credentials, но бросает при отсутствии кредов."""
        creds = self.resolve_publish_credentials(db, project_id, platform_key)
        if not creds.ok:
            raise PlatformCredentialsMissingError(creds.message)
        return creds


def get_platform_connection_service() -> PlatformConnectionService:
    """DI-фабрика сервиса подключений платформ."""
    return PlatformConnectionService()
