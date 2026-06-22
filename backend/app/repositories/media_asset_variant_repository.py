"""Репозиторий производных вариантов медиа (MediaAssetVariant).

Вариант — это улучшенная копия медиа-актива. Репозиторий инкапсулирует доступ
к БД: создание, выборку, обновление и агрегаты по статусам/типам.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.media_asset_variant import MediaAssetVariant
from app.schemas.media_enhancement import MediaAssetVariantCreate, MediaAssetVariantUpdate


class MediaAssetVariantNotFoundError(Exception):
    """Производный вариант медиа не найден."""

    def __init__(self, variant_id: int) -> None:
        self.variant_id = variant_id
        super().__init__(f"Вариант медиа id={variant_id} не найден")


def get_variant_by_id(db: Session, variant_id: int) -> MediaAssetVariant | None:
    """Вернуть вариант по id или None."""
    return db.get(MediaAssetVariant, variant_id)


def list_variants(
    db: Session,
    media_asset_id: int | None = None,
    project_id: int | None = None,
    status: str | None = None,
    variant_type: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MediaAssetVariant]:
    """Вернуть список вариантов с фильтрами и пагинацией."""
    stmt = select(MediaAssetVariant).order_by(MediaAssetVariant.id)
    if media_asset_id is not None:
        stmt = stmt.where(MediaAssetVariant.media_asset_id == media_asset_id)
    if project_id is not None:
        stmt = stmt.where(MediaAssetVariant.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaAssetVariant.status == status)
    if variant_type is not None:
        stmt = stmt.where(MediaAssetVariant.variant_type == variant_type)
    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def get_latest_variant_for_media(
    db: Session, media_asset_id: int, variant_type: str = "enhanced"
) -> MediaAssetVariant | None:
    """Вернуть самый свежий вариант данного типа для медиа-актива или None."""
    stmt = (
        select(MediaAssetVariant)
        .where(MediaAssetVariant.media_asset_id == media_asset_id)
        .where(MediaAssetVariant.variant_type == variant_type)
        .order_by(MediaAssetVariant.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def get_latest_approved_enhanced_variant(
    db: Session, media_asset_id: int
) -> MediaAssetVariant | None:
    """Вернуть самый свежий approved enhanced-вариант С готовым файлом (output_path).

    Для публикации годится только одобренная улучшенная копия, у которой реально
    есть сохранённый файл — поэтому фильтруем по ``status='approved'`` и
    ``output_path IS NOT NULL`` и берём один свежий ряд (без загрузки всех вариантов).
    """
    stmt = (
        select(MediaAssetVariant)
        .where(MediaAssetVariant.media_asset_id == media_asset_id)
        .where(MediaAssetVariant.variant_type == "enhanced")
        .where(MediaAssetVariant.status == "approved")
        .where(MediaAssetVariant.output_path.is_not(None))
        .order_by(MediaAssetVariant.id.desc())
        .limit(1)
    )
    return db.scalars(stmt).first()


def create_variant(db: Session, data: MediaAssetVariantCreate) -> MediaAssetVariant:
    """Создать производный вариант медиа."""
    variant = MediaAssetVariant(**data.model_dump())
    db.add(variant)
    db.commit()
    db.refresh(variant)
    return variant


def update_variant(
    db: Session, variant: MediaAssetVariant, data: MediaAssetVariantUpdate
) -> MediaAssetVariant:
    """Частично обновить вариант (только переданные поля)."""
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(variant, field, value)
    db.commit()
    db.refresh(variant)
    return variant


def mark_variant_status(db: Session, variant_id: int, status: str) -> MediaAssetVariant:
    """Сменить статус варианта по id. Бросает MediaAssetVariantNotFoundError."""
    variant = get_variant_by_id(db, variant_id)
    if variant is None:
        raise MediaAssetVariantNotFoundError(variant_id)
    variant.status = status
    db.commit()
    db.refresh(variant)
    return variant


def count_variants_by_project(db: Session, project_id: int) -> int:
    """Посчитать число вариантов проекта."""
    stmt = (
        select(func.count())
        .select_from(MediaAssetVariant)
        .where(MediaAssetVariant.project_id == project_id)
    )
    return db.scalar(stmt) or 0


def summarize_variants(
    db: Session, project_id: int | None = None
) -> tuple[int, dict[str, int], dict[str, int]]:
    """Вернуть (всего, по статусам, по типам) вариантов с фильтром по проекту."""
    by_status: dict[str, int] = {}
    by_type: dict[str, int] = {}

    rows = list_variants(db, project_id=project_id, limit=1_000_000)
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        by_type[row.variant_type] = by_type.get(row.variant_type, 0) + 1
    return len(rows), by_status, by_type
