"""Репозиторий публичных медиа-ссылок (media-proxy).

Работает только с ``token_hash`` — raw-токен сюда не передаётся и не хранится (хеширование
выполняет сервисный слой). Наружу raw-токен не выходит.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.public_media_link import PublicMediaLink


def create_link(db: Session, **fields: Any) -> PublicMediaLink:
    """Создать публичную ссылку (fields уже содержат token_hash, не raw-токен)."""
    link = PublicMediaLink(**fields)
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


def get_by_token_hash(db: Session, token_hash: str) -> PublicMediaLink | None:
    """Найти ссылку по хешу токена (или None)."""
    return db.scalars(
        select(PublicMediaLink).where(PublicMediaLink.token_hash == token_hash)
    ).first()


def get_by_id(db: Session, link_id: int) -> PublicMediaLink | None:
    """Найти ссылку по id (или None)."""
    return db.get(PublicMediaLink, link_id)


def list_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[PublicMediaLink]:
    """Ссылки проекта (свежие первыми)."""
    stmt = (
        select(PublicMediaLink)
        .where(PublicMediaLink.project_id == project_id)
        .order_by(PublicMediaLink.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.scalars(stmt).all())


def list_active_for_media_asset(db: Session, media_asset_id: int) -> list[PublicMediaLink]:
    """Активные ссылки для конкретного медиа-актива."""
    stmt = (
        select(PublicMediaLink)
        .where(
            PublicMediaLink.media_asset_id == media_asset_id,
            PublicMediaLink.status == "active",
        )
        .order_by(PublicMediaLink.id.desc())
    )
    return list(db.scalars(stmt).all())


def revoke_link(db: Session, link: PublicMediaLink, now: datetime) -> PublicMediaLink:
    """Отозвать ссылку (status=revoked)."""
    link.status = "revoked"
    link.revoked_at = now
    db.commit()
    db.refresh(link)
    return link


def increment_access(db: Session, link: PublicMediaLink, now: datetime) -> PublicMediaLink:
    """Увеличить счётчик обращений и обновить last_accessed_at."""
    link.hit_count = (link.hit_count or 0) + 1
    link.last_accessed_at = now
    db.commit()
    db.refresh(link)
    return link


def mark_expired(db: Session, link: PublicMediaLink) -> PublicMediaLink:
    """Пометить ссылку истёкшей (status=expired)."""
    link.status = "expired"
    db.commit()
    db.refresh(link)
    return link


def cleanup_expired(db: Session, now: datetime) -> int:
    """Пометить все просроченные активные ссылки как expired. Возврат — количество."""
    stmt = select(PublicMediaLink).where(
        PublicMediaLink.status == "active",
        PublicMediaLink.expires_at.is_not(None),
        PublicMediaLink.expires_at < now,
    )
    links = list(db.scalars(stmt).all())
    for link in links:
        link.status = "expired"
    if links:
        db.commit()
    return len(links)
