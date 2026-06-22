"""Репозиторий для работы с медиа-активами (MediaAsset).

Бизнес-уникальность медиафайла определяется его путём на Яндекс Диске
(``yandex_disk_path``). Метод upsert использует это, чтобы повторная
синхронизация не создавала дубликаты.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations.yandex_disk.client import YandexDiskResource
from app.models.media_asset import MediaAsset
from app.schemas.media_asset import MediaAssetCreate, MediaAssetUpdate


class MediaAssetNotFoundError(Exception):
    """Медиа-актив не найден в базе данных."""

    def __init__(self, media_asset_id: int) -> None:
        self.media_asset_id = media_asset_id
        super().__init__(f"Медиа-актив id={media_asset_id} не найден")


def get_media_asset_by_id(db: Session, media_asset_id: int) -> MediaAsset | None:
    """Вернуть медиа-актив по id или None."""
    return db.get(MediaAsset, media_asset_id)


def get_media_asset_by_path(db: Session, yandex_disk_path: str) -> MediaAsset | None:
    """Вернуть медиа-актив по пути на Яндекс Диске или None."""
    stmt = select(MediaAsset).where(MediaAsset.yandex_disk_path == yandex_disk_path)
    return db.scalars(stmt).first()


def list_media_assets(
    db: Session,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MediaAsset]:
    """Вернуть список медиа с фильтрами по проекту и статусу и пагинацией."""
    stmt = select(MediaAsset).order_by(MediaAsset.id)
    if project_id is not None:
        stmt = stmt.where(MediaAsset.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaAsset.status == status)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_media_assets_by_project(db: Session, project_id: int | None = None) -> list[MediaAsset]:
    """Вернуть ВСЕ медиа проекта (или всех проектов) без пагинации."""
    stmt = select(MediaAsset).order_by(MediaAsset.id)
    if project_id is not None:
        stmt = stmt.where(MediaAsset.project_id == project_id)
    return list(db.scalars(stmt).all())


def list_media_assets_by_path_prefix(
    db: Session, prefix: str, project_id: int | None = None
) -> list[MediaAsset]:
    """Вернуть медиа с ``yandex_disk_path``, начинающимся с префикса.

    Используется для поиска устаревших публичных медиа (``public://yandex/<slug>/``).
    ``autoescape`` экранирует ``%``/``_`` в префиксе.
    """
    stmt = select(MediaAsset).where(MediaAsset.yandex_disk_path.startswith(prefix, autoescape=True))
    if project_id is not None:
        stmt = stmt.where(MediaAsset.project_id == project_id)
    return list(db.scalars(stmt.order_by(MediaAsset.id)).all())


def count_media_assets(
    db: Session, project_id: int | None = None, status: str | None = None
) -> int:
    """Посчитать число медиа с фильтрами по проекту и статусу."""
    stmt = select(func.count()).select_from(MediaAsset)
    if project_id is not None:
        stmt = stmt.where(MediaAsset.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaAsset.status == status)
    return db.scalar(stmt) or 0


def create_media_asset(db: Session, data: MediaAssetCreate) -> MediaAsset:
    """Создать медиа-актив."""
    asset = MediaAsset(**data.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


def update_media_asset_tags(
    db: Session, media_asset: MediaAsset, tags: dict[str, Any]
) -> MediaAsset:
    """Обновить теги медиа-актива."""
    media_asset.tags = tags
    db.commit()
    db.refresh(media_asset)
    return media_asset


def update_media_asset_status(db: Session, media_asset: MediaAsset, status: str) -> MediaAsset:
    """Обновить статус медиа-актива."""
    media_asset.status = status
    db.commit()
    db.refresh(media_asset)
    return media_asset


def update_media_asset(db: Session, media_asset: MediaAsset, data: MediaAssetUpdate) -> MediaAsset:
    """Частично обновить медиа-актив (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(media_asset, field, value)
    db.commit()
    db.refresh(media_asset)
    return media_asset


def upsert_media_asset_from_disk_resource(
    db: Session,
    project_id: int,
    resource: YandexDiskResource,
    tags: dict[str, Any],
    source_type: str,
    license_type: str,
    status: str,
) -> tuple[MediaAsset, str]:
    """Создать или обновить медиа-актив по ресурсу Яндекс Диска.

    Уникальность — по ``resource.path`` (yandex_disk_path). Возвращает кортеж
    ``(asset, action)``, где ``action`` ∈ {"created", "updated", "unchanged"}.
    """
    existing = get_media_asset_by_path(db, resource.path)

    if existing is None:
        asset = MediaAsset(
            project_id=project_id,
            file_name=resource.name,
            yandex_disk_path=resource.path,
            source_type=source_type,
            license_type=license_type,
            tags=tags,
            status=status,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset, "created"

    changed = False
    if existing.file_name != resource.name:
        existing.file_name = resource.name
        changed = True
    if existing.source_type != source_type:
        existing.source_type = source_type
        changed = True
    if existing.license_type != license_type:
        existing.license_type = license_type
        changed = True
    if existing.status != status:
        existing.status = status
        changed = True
    if existing.tags != tags:
        existing.tags = tags
        changed = True

    if not changed:
        return existing, "unchanged"

    db.commit()
    db.refresh(existing)
    return existing, "updated"
