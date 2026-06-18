"""Сервис синхронизации медиа проекта с Яндекс Диска.

Сканирует папки проекта на Яндекс Диске, разбирает имена файлов через
``MediaTaggingService`` и сохраняет/обновляет записи ``MediaAsset``.
Скачивание файлов на этом этапе не выполняется.
"""

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.integrations.yandex_disk.client import (
    YandexDiskAuthError,
    YandexDiskClient,
    YandexDiskError,
    YandexDiskNotFoundError,
    YandexDiskResource,
)
from app.models.project import Project
from app.repositories import media_asset_repository, project_repository
from app.schemas.media_asset import MediaAssetSyncResult
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import get_default_scan_folders

logger = get_logger(__name__)

# Маркеры папок хранилища (подстроки в пути).
_FOLDER_INCOMING = "01_Входящие_на_разбор"
_FOLDER_APPROVED = "02_Одобренные_фото"
_FOLDER_VIDEO = "03_Видео"
_FOLDER_EXTERNAL = "04_Внешние_картинки_из_интернета"
_FOLDER_RESHOOT = "06_Нужно_переснять"


class ProjectNotFoundError(Exception):
    """Проект не найден в базе данных."""

    def __init__(self, identifier: object) -> None:
        self.identifier = identifier
        super().__init__(f"Проект не найден: {identifier}")


def classify_resource(path: str) -> tuple[str, str, str]:
    """По пути файла определить (source_type, license_type, status)."""
    if _FOLDER_EXTERNAL in path:
        return "external_stock", "external_needs_review", "needs_license_review"

    source_type = "internal"
    license_type = "company_owned"
    if _FOLDER_APPROVED in path:
        status = "approved"
    elif _FOLDER_VIDEO in path:
        status = "approved_video"
    elif _FOLDER_RESHOOT in path:
        status = "needs_reshoot"
    else:
        # 01_Входящие_на_разбор и всё прочее внутреннее — на разбор.
        status = "new"
    return source_type, license_type, status


class YandexDiskMediaSyncService:
    """Синхронизирует медиафайлы проекта с Яндекс Диска в таблицу media_assets."""

    def __init__(
        self,
        client: YandexDiskClient,
        tagging_service: MediaTaggingService,
    ) -> None:
        self._client = client
        self._tagging = tagging_service

    def sync_project_media(self, db: Session, project_id: int) -> MediaAssetSyncResult:
        """Синхронизировать медиа проекта по его id."""
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return self._sync(db, project)

    def sync_project_media_by_slug(self, db: Session, slug: str) -> MediaAssetSyncResult:
        """Синхронизировать медиа проекта по его slug."""
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            raise ProjectNotFoundError(slug)
        return self._sync(db, project)

    def _sync(self, db: Session, project: Project) -> MediaAssetSyncResult:
        folders = get_default_scan_folders(project.slug)
        result = MediaAssetSyncResult(project_id=project.id, project_slug=project.slug)

        for folder in folders:
            try:
                resources = self._client.list_files_recursive(folder)
            except YandexDiskNotFoundError:
                # Папки может не быть — не валим всю синхронизацию.
                result.errors.append(f"Папка не найдена: {folder}")
                logger.warning("Папка не найдена при синхронизации: %s", folder)
                continue
            except YandexDiskAuthError:
                # Проблема с токеном — это не локальная ошибка папки, прерываем всё.
                raise
            except YandexDiskError as exc:
                result.errors.append(f"Ошибка при сканировании {folder}: {exc}")
                logger.warning("Ошибка сканирования папки %s: %s", folder, exc)
                continue

            result.scanned_folders.append(folder)
            for resource in resources:
                self._process_resource(db, project.id, project.slug, resource, result)

        logger.info(
            "Синхронизация проекта %s завершена: найдено=%d, создано=%d, "
            "обновлено=%d, пропущено=%d",
            project.slug,
            result.found_files,
            result.created,
            result.updated,
            result.skipped,
        )
        return result

    def _process_resource(
        self,
        db: Session,
        project_id: int,
        project_slug: str,
        resource: YandexDiskResource,
        result: MediaAssetSyncResult,
    ) -> None:
        result.found_files += 1
        source_type, license_type, status = classify_resource(resource.path)
        tags = self._tagging.analyze_file_name(
            resource.name,
            project_slug=project_slug,
            yandex_disk_path=resource.path,
            source_type=source_type,
        )

        _asset, action = media_asset_repository.upsert_media_asset_from_disk_resource(
            db,
            project_id=project_id,
            resource=resource,
            tags=tags,
            source_type=source_type,
            license_type=license_type,
            status=status,
        )
        if action == "created":
            result.created += 1
        elif action == "updated":
            result.updated += 1
        else:
            result.skipped += 1
