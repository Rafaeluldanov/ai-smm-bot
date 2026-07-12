"""Репозиторий fingerprint медиа (media_fingerprints).

Сигнатуры/хэши не содержат секретов, raw bytes и внутренних путей к файлам (обеспечивает
сервисный слой). Все выборки фильтруют по ``project_id`` (изоляция — на API/сервисном слое).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.media_fingerprint import MediaFingerprint


def create_fingerprint(db: Session, **fields: Any) -> MediaFingerprint:
    """Создать fingerprint медиа."""
    fingerprint = MediaFingerprint(**fields)
    db.add(fingerprint)
    db.commit()
    db.refresh(fingerprint)
    return fingerprint


def get_by_id(db: Session, fingerprint_id: int) -> MediaFingerprint | None:
    """Fingerprint по id (или None)."""
    return db.get(MediaFingerprint, fingerprint_id)


def get_latest_for_asset(
    db: Session, project_id: int, media_asset_id: int
) -> MediaFingerprint | None:
    """Последний fingerprint медиа проекта."""
    stmt = (
        select(MediaFingerprint)
        .where(
            MediaFingerprint.project_id == project_id,
            MediaFingerprint.media_asset_id == media_asset_id,
        )
        .order_by(MediaFingerprint.id.desc())
    )
    return db.scalars(stmt).first()


def list_for_project(
    db: Session,
    project_id: int,
    status: str | None = None,
    media_asset_id: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MediaFingerprint]:
    """Fingerprint проекта (свежие первыми) с фильтрами статус/медиа."""
    stmt = select(MediaFingerprint).where(MediaFingerprint.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaFingerprint.status == status)
    if media_asset_id is not None:
        stmt = stmt.where(MediaFingerprint.media_asset_id == media_asset_id)
    stmt = stmt.order_by(MediaFingerprint.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_by_sha256(db: Session, project_id: int, sha256: str) -> list[MediaFingerprint]:
    """Fingerprint проекта с данным file sha256 (точные дубли байтов)."""
    stmt = select(MediaFingerprint).where(
        MediaFingerprint.project_id == project_id,
        MediaFingerprint.file_sha256 == sha256,
    )
    return list(db.scalars(stmt).all())


def list_by_perceptual_hash(
    db: Session, project_id: int, perceptual_hash: str
) -> list[MediaFingerprint]:
    """Fingerprint проекта с данным perceptual hash (кандидаты в визуальные дубли)."""
    stmt = select(MediaFingerprint).where(
        MediaFingerprint.project_id == project_id,
        MediaFingerprint.perceptual_hash == perceptual_hash,
    )
    return list(db.scalars(stmt).all())


def latest_per_asset_for_project(db: Session, project_id: int) -> list[MediaFingerprint]:
    """Последний fingerprint на каждый медиа-ассет проекта (для сравнения/кластеров)."""
    latest: dict[int, MediaFingerprint] = {}
    for row in list_for_project(db, project_id, limit=5000):  # свежие первыми
        latest.setdefault(row.media_asset_id, row)
    return list(latest.values())


def update_fingerprint(
    db: Session, fingerprint: MediaFingerprint, **fields: Any
) -> MediaFingerprint:
    """Обновить поля fingerprint."""
    for field, value in fields.items():
        setattr(fingerprint, field, value)
    db.commit()
    db.refresh(fingerprint)
    return fingerprint


def delete_old_fingerprints(db: Session, project_id: int, media_asset_id: int, keep: int) -> int:
    """Оставить только ``keep`` свежих fingerprint для медиа; вернуть число удалённых."""
    stmt = (
        select(MediaFingerprint.id)
        .where(
            MediaFingerprint.project_id == project_id,
            MediaFingerprint.media_asset_id == media_asset_id,
        )
        .order_by(MediaFingerprint.id.desc())
    )
    ids = list(db.scalars(stmt).all())
    to_delete = ids[max(0, keep) :]
    if not to_delete:
        return 0
    for fingerprint_id in to_delete:
        obj = db.get(MediaFingerprint, fingerprint_id)
        if obj is not None:
            db.delete(obj)
    db.commit()
    return len(to_delete)


def list_missing_fingerprints_for_project(
    db: Session, project_id: int, limit: int = 500
) -> list[MediaAsset]:
    """Медиа проекта без единого fingerprint (кандидаты на расчёт)."""
    fingerprinted = set(
        db.scalars(
            select(MediaFingerprint.media_asset_id).where(MediaFingerprint.project_id == project_id)
        ).all()
    )
    stmt = (
        select(MediaAsset).where(MediaAsset.project_id == project_id).order_by(MediaAsset.id.asc())
    )
    out: list[MediaAsset] = []
    for asset in db.scalars(stmt).all():
        if asset.id not in fingerprinted:
            out.append(asset)
        if len(out) >= limit:
            break
    return out
