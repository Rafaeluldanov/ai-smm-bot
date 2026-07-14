"""Репозиторий media-proxy delivery layer (v0.6.2).

Фасад над существующим ``public_media_link_repository`` (токены доставки) + владелец НОВОГО
журнала обращений ``media_proxy_access_logs``. Токены хранятся только как ``token_hash`` (raw-токен
сюда не передаётся); журнал не хранит IP/UA (только их хеши) и не хранит внутренних путей.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_proxy_access_log import MediaProxyAccessLog
from app.models.public_media_link import PublicMediaLink
from app.repositories import public_media_link_repository as _links


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Токены доставки (фасад над public_media_link_repository)                      #
# ---------------------------------------------------------------------------- #


def create_token(db: Session, **fields: Any) -> PublicMediaLink:
    """Создать токен доставки (fields содержат token_hash/transform/token_type/max_requests)."""
    return _links.create_link(db, **fields)


def get_token_by_hash(db: Session, token_hash: str) -> PublicMediaLink | None:
    """Найти токен по хешу (или None)."""
    return _links.get_by_token_hash(db, token_hash)


def get_token_by_id(db: Session, token_id: int) -> PublicMediaLink | None:
    """Найти токен по id (или None)."""
    return _links.get_by_id(db, token_id)


def disable_token(db: Session, token: PublicMediaLink) -> PublicMediaLink:
    """Отключить токен (soft: status=revoked)."""
    return _links.revoke_link(db, token, _now())


def increase_usage(db: Session, token: PublicMediaLink) -> PublicMediaLink:
    """Инкремент счётчика обращений (request_count = hit_count) + last_used_at."""
    return _links.increment_access(db, token, _now())


def list_asset_tokens(db: Session, media_asset_id: int) -> list[PublicMediaLink]:
    """Активные токены доставки для медиа-актива."""
    return _links.list_active_for_media_asset(db, media_asset_id)


def cleanup_expired_tokens(db: Session, now: datetime | None = None) -> int:
    """Пометить просроченные активные токены как expired (возвращает число)."""
    return _links.cleanup_expired(db, now or _now())


# ---------------------------------------------------------------------------- #
# Журнал обращений (media_proxy_access_logs)                                    #
# ---------------------------------------------------------------------------- #


def create_access_log(
    db: Session,
    *,
    public_media_link_id: int | None,
    media_asset_id: int | None,
    status: int,
    request_ip_hash: str | None = None,
    user_agent_hash: str | None = None,
    response_type: str | None = None,
    response_size: int | None = None,
    transform: str | None = None,
) -> MediaProxyAccessLog:
    """Записать обращение к media-proxy (без IP/UA/секретов — только хеши)."""
    log = MediaProxyAccessLog(
        public_media_link_id=public_media_link_id,
        media_asset_id=media_asset_id,
        status=int(status),
        request_ip_hash=request_ip_hash,
        user_agent_hash=user_agent_hash,
        response_type=response_type,
        response_size=response_size,
        transform=transform,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def list_access_logs(
    db: Session, media_asset_id: int, limit: int = 50
) -> list[MediaProxyAccessLog]:
    """Последние обращения по медиа-активу (свежие первыми)."""
    stmt = (
        select(MediaProxyAccessLog)
        .where(MediaProxyAccessLog.media_asset_id == media_asset_id)
        .order_by(MediaProxyAccessLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_access_logs_for_link(
    db: Session, public_media_link_id: int, limit: int = 50
) -> list[MediaProxyAccessLog]:
    """Последние обращения по токену (свежие первыми)."""
    stmt = (
        select(MediaProxyAccessLog)
        .where(MediaProxyAccessLog.public_media_link_id == public_media_link_id)
        .order_by(MediaProxyAccessLog.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def public_access_log_view(log: MediaProxyAccessLog) -> dict[str, Any]:
    """Безопасное представление записи журнала (без секретов/IP/UA)."""
    return {
        "id": log.id,
        "public_media_link_id": log.public_media_link_id,
        "media_asset_id": log.media_asset_id,
        "status": log.status,
        "response_type": log.response_type,
        "response_size": log.response_size,
        "transform": log.transform,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
