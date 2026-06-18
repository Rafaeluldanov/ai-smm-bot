"""Сервис анализа и ретегирования медиа.

Объединяет тегирование (``MediaTaggingService``), доступ к данным
(репозитории) и правила статусов (``MediaStatusService``). Реального
анализа изображений и обращений к внешним сервисам здесь нет.
"""

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.media_asset import MediaAsset
from app.repositories import media_asset_repository, project_repository
from app.repositories.media_asset_repository import MediaAssetNotFoundError
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService
from app.services.project_media_paths import UnknownProjectError, get_project_disk_root
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

# Группы тегов, по которым строится сводка.
_SUMMARY_GROUPS = [
    "products",
    "technologies",
    "details",
    "materials",
    "colors",
    "categories",
    "use_cases",
    "audiences",
]

# Минимум одобренных медиа на важную тему, ниже которого предлагаем досъёмку.
_MIN_APPROVED_PER_TAG = 2

# Целевые темы для рекомендаций по досъёмке: (тег, группа тега).
_TARGET_TAGS: dict[str, list[tuple[str, str]]] = {
    "teeon": [
        ("футболка", "products"),
        ("худи", "products"),
        ("шоппер", "products"),
        ("шелкография", "technologies"),
        ("dtf", "technologies"),
        ("вышивка", "technologies"),
        ("жаккард", "details"),
    ],
    "fabric-souvenirs": [
        ("кружка", "products"),
        ("ручка", "products"),
        ("пакет", "products"),
        ("уф-печать", "technologies"),
        ("тампопечать", "technologies"),
        ("гравировка", "technologies"),
        ("шелкография", "technologies"),
    ],
}


class MediaAnalysisService:
    """Повторный анализ/тегирование медиа, сводки и рекомендации по съёмке."""

    def __init__(
        self,
        tagging_service: MediaTaggingService,
        status_service: MediaStatusService,
    ) -> None:
        self._tagging = tagging_service
        self._status = status_service

    def analyze_media_asset(
        self, db: Session, media_asset_id: int, save: bool = True
    ) -> dict[str, Any]:
        """Проанализировать один медиа-актив. При save=True сохранить теги."""
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None:
            raise MediaAssetNotFoundError(media_asset_id)

        project = project_repository.get_project_by_id(db, asset.project_id)
        project_slug = project.slug if project is not None else None

        tags = self._tagging.analyze_file_name(
            asset.file_name,
            project_slug=project_slug,
            yandex_disk_path=asset.yandex_disk_path,
            source_type=asset.source_type,
        )
        if save:
            media_asset_repository.update_media_asset_tags(db, asset, tags)

        return {
            "media_asset_id": asset.id,
            "project_id": asset.project_id,
            "project_slug": project_slug,
            "file_name": asset.file_name,
            "saved": save,
            "tags": tags,
        }

    def retag_media_asset(self, db: Session, media_asset_id: int) -> MediaAsset:
        """Повторно протегировать один медиа-актив и вернуть его."""
        self.analyze_media_asset(db, media_asset_id, save=True)
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None:  # практически недостижимо — только что обновляли
            raise MediaAssetNotFoundError(media_asset_id)
        return asset

    def retag_project_media(self, db: Session, project_id: int) -> dict[str, Any]:
        """Повторно протегировать все медиа проекта (по id)."""
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return self._retag_all(db, project.id, project.slug)

    def retag_project_media_by_slug(self, db: Session, slug: str) -> dict[str, Any]:
        """Повторно протегировать все медиа проекта (по slug)."""
        project = project_repository.get_project_by_slug(db, slug)
        if project is None:
            raise ProjectNotFoundError(slug)
        return self._retag_all(db, project.id, project.slug)

    def _retag_all(self, db: Session, project_id: int, project_slug: str) -> dict[str, Any]:
        assets = media_asset_repository.list_media_assets_by_project(db, project_id)
        processed = 0
        updated = 0
        skipped = 0
        errors: list[str] = []

        for asset in assets:
            processed += 1
            try:
                new_tags = self._tagging.analyze_file_name(
                    asset.file_name,
                    project_slug=project_slug,
                    yandex_disk_path=asset.yandex_disk_path,
                    source_type=asset.source_type,
                )
                if asset.tags != new_tags:
                    media_asset_repository.update_media_asset_tags(db, asset, new_tags)
                    updated += 1
                else:
                    skipped += 1
            except Exception as exc:  # устойчивость к ошибке отдельного файла
                errors.append(f"asset id={asset.id}: {exc}")
                logger.warning("Ошибка ретегирования asset id=%s: %s", asset.id, exc)

        return {
            "project_id": project_id,
            "project_slug": project_slug,
            "processed": processed,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    def get_tags_summary(self, db: Session, project_id: int | None = None) -> dict[str, Any]:
        """Собрать частоты тегов по группам (для будущего выбора тем)."""
        assets = media_asset_repository.list_media_assets_by_project(db, project_id)
        counters: dict[str, dict[str, int]] = {group: {} for group in _SUMMARY_GROUPS}

        for asset in assets:
            tags = asset.tags or {}
            for group in _SUMMARY_GROUPS:
                for value in tags.get(group, []) or []:
                    counters[group][value] = counters[group].get(value, 0) + 1

        summary: dict[str, Any] = {"project_id": project_id, "total_assets": len(assets)}
        for group in _SUMMARY_GROUPS:
            ordered = sorted(counters[group].items(), key=lambda kv: (-kv[1], kv[0]))
            summary[group] = dict(ordered)
        return summary

    def suggest_shooting_tasks(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Предложить задачи на досъёмку по темам с нехваткой approved-медиа."""
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)

        targets = _TARGET_TAGS.get(project.slug, [])
        try:
            reshoot_folder = f"{get_project_disk_root(project.slug)}/06_Нужно_переснять"
        except UnknownProjectError:
            reshoot_folder = ""

        approved = [
            asset
            for asset in media_asset_repository.list_media_assets_by_project(db, project_id)
            if asset.status == "approved"
        ]

        tasks: list[dict[str, Any]] = []
        for tag, tag_group in targets:
            count = sum(1 for asset in approved if tag in (asset.tags.get(tag_group) or []))
            if count < _MIN_APPROVED_PER_TAG:
                tasks.append(
                    {
                        "project_id": project.id,
                        "project_slug": project.slug,
                        "missing_tag": tag,
                        "tag_group": tag_group,
                        "reason": f"Недостаточно одобренных медиа по теме (approved: {count})",
                        "suggested_folder": reshoot_folder,
                        "suggested_shots": [
                            f"{tag}: общий план",
                            f"{tag}: крупный план нанесения/детали",
                            f"{tag}: на модели или в интерьере",
                        ],
                    }
                )
        return tasks
