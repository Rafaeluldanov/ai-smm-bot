"""Синхронизация медиа проекта по ПУБЛИЧНОЙ ссылке Яндекс Диска.

Альтернатива приватному OAuth-режиму (``YandexDiskMediaSyncService``): читает
публичную папку SMM без токена. Внутри SMM лежат проектные папки (например,
«Тион» и «Фабрика сувениров»); доступ к ним ограничен правилами проекта:

    teeon            → ТОЛЬКО «Тион»;
    fabric-souvenirs → «Фабрика сувениров» И «Тион».

Файлы НЕ скачиваются — сохраняются только метаданные ``MediaAsset`` (имя, путь,
теги). Сеть вызывается только публичным клиентом; в тестах он подменяется.
"""

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.integrations.yandex_disk.client import (
    YandexDiskError,
    YandexDiskNotFoundError,
    YandexDiskPublicClient,
    YandexDiskPublicResource,
)
from app.models.project import Project
from app.repositories import media_asset_repository, project_repository
from app.schemas.media_asset import MediaAssetCreate, MediaAssetSyncResult, MediaAssetUpdate
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import (
    is_public_folder_allowed_for_project,
    is_public_path_allowed_for_project,
)
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

# Запас по глубине рекурсии: реальная структура SMM мелкая (SMM/Проект/файлы),
# поэтому 10 уровней с большим запасом исключают потерю файлов в подпапках.
_PUBLIC_SCAN_MAX_DEPTH = 10

logger = get_logger(__name__)


class PublicLinkNotConfiguredError(Exception):
    """Не задана публичная ссылка Яндекс Диска (YANDEX_DISK_PUBLIC_SMM_URL)."""

    def __init__(self) -> None:
        super().__init__("Публичная ссылка Яндекс Диска не настроена (YANDEX_DISK_PUBLIC_SMM_URL)")


class PublicYandexDiskMediaSyncService:
    """Синхронизирует медиа проекта из публичной папки SMM (без токена)."""

    def __init__(
        self,
        client: YandexDiskPublicClient,
        tagging_service: MediaTaggingService,
        public_key: str | None,
        root_folder: str = "SMM",
    ) -> None:
        self._client = client
        self._tagging = tagging_service
        self._public_key = public_key
        self._root_folder = root_folder

    def sync_project_media_from_public_link(
        self, db: Session, project_id: int
    ) -> MediaAssetSyncResult:
        """Синхронизировать медиа проекта по id из публичной ссылки."""
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return self._sync(db, project)

    def sync_project_media_by_slug_from_public_link(
        self, db: Session, slug: str
    ) -> MediaAssetSyncResult:
        """Синхронизировать медиа проекта по slug из публичной ссылки."""
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            raise ProjectNotFoundError(slug)
        return self._sync(db, project)

    # --- Внутреннее ---

    def _sync(self, db: Session, project: Project) -> MediaAssetSyncResult:
        if not self._public_key:
            raise PublicLinkNotConfiguredError()
        public_key = self._public_key

        result = MediaAssetSyncResult(project_id=project.id, project_slug=project.slug)
        allowed_dirs = self._discover_allowed_dirs(public_key, project.slug, result)
        if not allowed_dirs:
            result.errors.append(
                f"Не найдено разрешённых папок для проекта '{project.slug}' в публичной ссылке"
            )

        for directory in allowed_dirs:
            result.scanned_folders.append(directory.path)
            try:
                files = self._client.list_public_files_recursive(
                    public_key, directory.path, max_depth=_PUBLIC_SCAN_MAX_DEPTH
                )
            except YandexDiskNotFoundError:
                result.errors.append(f"Папка не найдена: {directory.path}")
                continue
            except YandexDiskError as exc:
                result.errors.append(f"Ошибка при сканировании {directory.path}: {exc}")
                continue
            for file_resource in files:
                self._process_file(db, project, file_resource, result)

        logger.info(
            "Публичная синхронизация %s: папок=%d, найдено=%d, создано=%d, обновлено=%d",
            project.slug,
            len(result.scanned_folders),
            result.found_files,
            result.created,
            result.updated,
        )
        return result

    def _scan_base(self) -> str:
        folder = self._root_folder.strip("/")
        return f"/{folder}" if folder else "/"

    def _discover_allowed_dirs(
        self, public_key: str, slug: str, result: MediaAssetSyncResult
    ) -> list[YandexDiskPublicResource]:
        scan_base = self._scan_base()
        dirs, errors = self._safe_list_dirs(public_key, scan_base)
        allowed = [d for d in dirs if is_public_folder_allowed_for_project(slug, d.name)]
        if allowed:
            return allowed
        # Фолбэк: публичная ссылка может вести прямо на папку SMM.
        if scan_base != "/":
            root_dirs, root_errors = self._safe_list_dirs(public_key, "/")
            root_allowed = [
                d for d in root_dirs if is_public_folder_allowed_for_project(slug, d.name)
            ]
            if root_allowed:
                return root_allowed
            result.errors.extend(errors or root_errors)
        else:
            result.errors.extend(errors)
        return []

    def _safe_list_dirs(
        self, public_key: str, path: str
    ) -> tuple[list[YandexDiskPublicResource], list[str]]:
        try:
            resources = self._client.list_public_resources(public_key, path)
        except YandexDiskNotFoundError:
            return [], [f"Публичная папка не найдена: {path}"]
        except YandexDiskError as exc:
            return [], [f"Ошибка чтения публичной папки {path}: {exc}"]
        return [r for r in resources if r.is_dir], []

    def _process_file(
        self,
        db: Session,
        project: Project,
        file_resource: YandexDiskPublicResource,
        result: MediaAssetSyncResult,
    ) -> None:
        result.found_files += 1
        if not file_resource.is_media:
            result.skipped += 1
            return
        # Защита от чужой проектной папки, вложенной в разрешённую: проверяем
        # ВЕСЬ путь файла, а не только корневую папку (teeon ⊄ «Фабрика сувениров»).
        if not is_public_path_allowed_for_project(project.slug, file_resource.path):
            result.skipped += 1
            return

        # Путь содержит slug проекта: один и тот же файл из общей папки «Тион»
        # становится отдельным MediaAsset для каждого проекта (без коллизий).
        disk_path = f"public://yandex/{project.slug}{file_resource.path}"
        tags = self._tagging.analyze_file_name(
            file_resource.name,
            project_slug=project.slug,
            yandex_disk_path=disk_path,
            source_type="internal",
        )
        title = self._title_from_name(file_resource.name)
        description = f"Источник: публичная папка Яндекс Диска ({self._root_folder})"

        existing = media_asset_repository.get_media_asset_by_path(db, disk_path)
        if existing is None:
            media_asset_repository.create_media_asset(
                db,
                MediaAssetCreate(
                    project_id=project.id,
                    file_name=file_resource.name,
                    yandex_disk_path=disk_path,
                    source_type="internal",
                    license_type="company_owned",
                    title=title,
                    description=description,
                    tags=tags,
                    status="new",
                ),
            )
            result.created += 1
            return

        if existing.tags != tags or existing.title != title or existing.description != description:
            media_asset_repository.update_media_asset(
                db, existing, MediaAssetUpdate(tags=tags, title=title, description=description)
            )
            result.updated += 1
        else:
            result.skipped += 1

    @staticmethod
    def _title_from_name(name: str) -> str:
        return name.rsplit(".", 1)[0] if "." in name else name
