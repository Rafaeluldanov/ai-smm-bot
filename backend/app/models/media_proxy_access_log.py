"""Модель журнала обращений к media-proxy (аналитика доставки) — v0.6.2.

Пишет ТОЛЬКО безопасную аналитику по каждому обращению к публичной ссылке:
- НЕ хранит IP и User-Agent (только их sha256-хеш);
- НЕ хранит raw-токен и внутренние пути файлов;
- статус — HTTP-код ответа (200/403/404/410), размер и тип ответа, применённая трансформация.
"""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# HTTP-коды, которыми помечается обращение.
MEDIA_PROXY_ACCESS_STATUSES: tuple[int, ...] = (200, 403, 404, 410)


class MediaProxyAccessLog(Base, TimestampMixin):
    """Запись об одном обращении к публичной media-ссылке (без секретов/IP/UA)."""

    __tablename__ = "media_proxy_access_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_media_link_id: Mapped[int | None] = mapped_column(
        ForeignKey("public_media_links.id", ondelete="SET NULL"), default=None, index=True
    )
    media_asset_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    # Только хеши — сырой IP/UA не хранятся.
    request_ip_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    status: Mapped[int] = mapped_column(Integer, default=200, index=True, nullable=False)
    response_type: Mapped[str | None] = mapped_column(String(100), default=None)
    response_size: Mapped[int | None] = mapped_column(Integer, default=None)
    transform: Mapped[str | None] = mapped_column(String(30), default=None)
