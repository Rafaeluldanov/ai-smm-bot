"""Репозиторий кластеров дублей медиа (media_duplicate_clusters).

``reasons``/``cluster_metadata`` не содержат секретов и внутренних путей (обеспечивает
сервисный слой). Все выборки фильтруют по ``project_id`` (изоляция — на API/сервисном слое).
Файлы НЕ удаляются; авто-скрытие/удаление выключено.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_duplicate_cluster import MediaDuplicateCluster


def create_cluster(db: Session, **fields: Any) -> MediaDuplicateCluster:
    """Создать кластер дублей."""
    cluster = MediaDuplicateCluster(**fields)
    db.add(cluster)
    db.commit()
    db.refresh(cluster)
    return cluster


def get_by_id(db: Session, cluster_id: int) -> MediaDuplicateCluster | None:
    """Кластер по id (или None)."""
    return db.get(MediaDuplicateCluster, cluster_id)


def list_for_project(
    db: Session,
    project_id: int,
    status: str | None = None,
    cluster_type: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[MediaDuplicateCluster]:
    """Кластеры проекта (свежие первыми) с фильтрами статус/тип."""
    stmt = select(MediaDuplicateCluster).where(MediaDuplicateCluster.project_id == project_id)
    if status is not None:
        stmt = stmt.where(MediaDuplicateCluster.status == status)
    if cluster_type is not None:
        stmt = stmt.where(MediaDuplicateCluster.cluster_type == cluster_type)
    stmt = stmt.order_by(MediaDuplicateCluster.id.desc()).limit(limit).offset(offset)
    return list(db.scalars(stmt).all())


def list_active_for_project(
    db: Session, project_id: int, limit: int = 200
) -> list[MediaDuplicateCluster]:
    """Активные кластеры проекта (не reviewed/ignored/resolved)."""
    stmt = (
        select(MediaDuplicateCluster)
        .where(
            MediaDuplicateCluster.project_id == project_id,
            MediaDuplicateCluster.status == "active",
        )
        .order_by(MediaDuplicateCluster.similarity_score.desc(), MediaDuplicateCluster.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def find_cluster_for_media_asset(
    db: Session, project_id: int, media_asset_id: int
) -> MediaDuplicateCluster | None:
    """Активный кластер, содержащий данный медиа-ассет (проверка вхождения в Python)."""
    for cluster in list_active_for_project(db, project_id, limit=500):
        members = cluster.member_media_asset_ids or []
        if media_asset_id in members or cluster.canonical_media_asset_id == media_asset_id:
            return cluster
    return None


def update_cluster(
    db: Session, cluster: MediaDuplicateCluster, **fields: Any
) -> MediaDuplicateCluster:
    """Обновить поля кластера."""
    for field, value in fields.items():
        setattr(cluster, field, value)
    db.commit()
    db.refresh(cluster)
    return cluster


def _mark(
    db: Session, cluster: MediaDuplicateCluster, status: str, user_id: int | None
) -> MediaDuplicateCluster:
    return update_cluster(
        db,
        cluster,
        status=status,
        reviewed_by_user_id=user_id,
        reviewed_at=datetime.now(UTC),
    )


def mark_reviewed(
    db: Session, cluster: MediaDuplicateCluster, user_id: int | None = None
) -> MediaDuplicateCluster:
    """Отметить кластер просмотренным."""
    return _mark(db, cluster, "reviewed", user_id)


def mark_ignored(
    db: Session, cluster: MediaDuplicateCluster, user_id: int | None = None
) -> MediaDuplicateCluster:
    """Отметить кластер проигнорированным."""
    return _mark(db, cluster, "ignored", user_id)


def mark_resolved(
    db: Session, cluster: MediaDuplicateCluster, user_id: int | None = None
) -> MediaDuplicateCluster:
    """Отметить кластер разрешённым (клиент разобрался с дублями)."""
    return _mark(db, cluster, "resolved", user_id)


def delete_old_clusters(db: Session, project_id: int, keep: int) -> int:
    """Оставить только ``keep`` свежих кластеров проекта; вернуть число удалённых."""
    stmt = (
        select(MediaDuplicateCluster.id)
        .where(MediaDuplicateCluster.project_id == project_id)
        .order_by(MediaDuplicateCluster.id.desc())
    )
    ids = list(db.scalars(stmt).all())
    to_delete = ids[max(0, keep) :]
    for cluster_id in to_delete:
        obj = db.get(MediaDuplicateCluster, cluster_id)
        if obj is not None:
            db.delete(obj)
    db.commit()
    return len(to_delete)
