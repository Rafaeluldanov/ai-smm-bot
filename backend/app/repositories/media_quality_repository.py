"""Репозиторий снимков качества медиа (media_quality_snapshots).

``source_signals``/``snapshot_metadata`` секретов и внутренних путей к файлам не содержат
(обеспечивает сервисный слой). Все выборки фильтруют по ``project_id`` (изоляция — на
API/сервисном слое).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_quality_snapshot import MediaQualitySnapshot


def create_snapshot(db: Session, **fields: Any) -> MediaQualitySnapshot:
    """Создать снимок качества медиа."""
    snapshot = MediaQualitySnapshot(**fields)
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_by_id(db: Session, snapshot_id: int) -> MediaQualitySnapshot | None:
    """Снимок по id (или None)."""
    return db.get(MediaQualitySnapshot, snapshot_id)


def get_latest_for_asset(
    db: Session, project_id: int, media_asset_id: int
) -> MediaQualitySnapshot | None:
    """Последний снимок для медиа проекта (без учёта платформы)."""
    stmt = (
        select(MediaQualitySnapshot)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            MediaQualitySnapshot.media_asset_id == media_asset_id,
        )
        .order_by(MediaQualitySnapshot.id.desc())
    )
    return db.scalars(stmt).first()


def get_latest_for_asset_platform(
    db: Session, project_id: int, media_asset_id: int, platform_key: str | None
) -> MediaQualitySnapshot | None:
    """Последний снимок для медиа проекта под конкретную платформу."""
    stmt = (
        select(MediaQualitySnapshot)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            MediaQualitySnapshot.media_asset_id == media_asset_id,
            MediaQualitySnapshot.platform_key == platform_key,
        )
        .order_by(MediaQualitySnapshot.id.desc())
    )
    return db.scalars(stmt).first()


def list_for_project(
    db: Session,
    project_id: int,
    platform_key: str | None = None,
    status: str | None = None,
    min_score: int | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MediaQualitySnapshot]:
    """Снимки проекта (свежие первыми) с фильтрами платформа/статус/минимальный балл."""
    stmt = select(MediaQualitySnapshot).where(MediaQualitySnapshot.project_id == project_id)
    if platform_key is not None:
        stmt = stmt.where(MediaQualitySnapshot.platform_key == platform_key)
    if status is not None:
        stmt = stmt.where(MediaQualitySnapshot.status == status)
    if min_score is not None:
        stmt = stmt.where(MediaQualitySnapshot.overall_score >= min_score)
    stmt = stmt.order_by(MediaQualitySnapshot.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_best_for_project(
    db: Session, project_id: int, limit: int = 20
) -> list[MediaQualitySnapshot]:
    """Лучшие медиа проекта (по overall_score, свежие снимки)."""
    stmt = (
        select(MediaQualitySnapshot)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            MediaQualitySnapshot.overall_score.is_not(None),
        )
        .order_by(MediaQualitySnapshot.overall_score.desc(), MediaQualitySnapshot.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_weak_for_project(
    db: Session, project_id: int, max_score: int | None = None, limit: int = 20
) -> list[MediaQualitySnapshot]:
    """Слабые медиа проекта (overall_score ниже порога или статус weak/needs_tags)."""
    stmt = select(MediaQualitySnapshot).where(MediaQualitySnapshot.project_id == project_id)
    if max_score is not None:
        stmt = stmt.where(
            MediaQualitySnapshot.overall_score.is_not(None),
            MediaQualitySnapshot.overall_score < max_score,
        )
    else:
        stmt = stmt.where(MediaQualitySnapshot.status.in_(("weak", "needs_tags")))
    stmt = stmt.order_by(MediaQualitySnapshot.overall_score.asc(), MediaQualitySnapshot.id.desc())
    return list(db.scalars(stmt.limit(limit)).all())


def list_duplicates_for_project(
    db: Session, project_id: int, limit: int = 50
) -> list[MediaQualitySnapshot]:
    """Медиа-снимки с признаком дубля (duplicate_of указан или статус duplicate)."""
    stmt = (
        select(MediaQualitySnapshot)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            (MediaQualitySnapshot.duplicate_of_media_asset_id.is_not(None))
            | (MediaQualitySnapshot.status == "duplicate"),
        )
        .order_by(MediaQualitySnapshot.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def list_recently_used_media(
    db: Session, project_id: int, limit: int = 50
) -> list[MediaQualitySnapshot]:
    """Снимки медиа, недавно использованного (recent_usage_count > 0)."""
    stmt = (
        select(MediaQualitySnapshot)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            MediaQualitySnapshot.recent_usage_count > 0,
        )
        .order_by(MediaQualitySnapshot.recent_usage_count.desc(), MediaQualitySnapshot.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def update_snapshot(
    db: Session, snapshot: MediaQualitySnapshot, **fields: Any
) -> MediaQualitySnapshot:
    """Обновить поля снимка."""
    for field, value in fields.items():
        setattr(snapshot, field, value)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def delete_old_snapshots(db: Session, project_id: int, media_asset_id: int, keep: int) -> int:
    """Оставить только ``keep`` свежих снимков для медиа; вернуть число удалённых."""
    stmt = (
        select(MediaQualitySnapshot.id)
        .where(
            MediaQualitySnapshot.project_id == project_id,
            MediaQualitySnapshot.media_asset_id == media_asset_id,
        )
        .order_by(MediaQualitySnapshot.id.desc())
    )
    ids = list(db.scalars(stmt).all())
    to_delete = ids[max(0, keep) :]
    if not to_delete:
        return 0
    for snapshot_id in to_delete:
        obj = db.get(MediaQualitySnapshot, snapshot_id)
        if obj is not None:
            db.delete(obj)
    db.commit()
    return len(to_delete)


def get_dashboard_summary(
    db: Session, project_id: int, platform_key: str | None = None
) -> dict[str, Any]:
    """Лёгкая агрегированная сводка (counts by status + средний overall). Дедуп — в сервисе."""
    rows = list_for_project(db, project_id, platform_key=platform_key, limit=1000)
    by_status: dict[str, int] = {}
    scores: list[int] = []
    for row in rows:
        by_status[row.status] = by_status.get(row.status, 0) + 1
        if row.overall_score is not None:
            scores.append(row.overall_score)
    return {
        "total_snapshots": len(rows),
        "by_status": by_status,
        "avg_overall": round(sum(scores) / len(scores), 1) if scores else 0.0,
    }
