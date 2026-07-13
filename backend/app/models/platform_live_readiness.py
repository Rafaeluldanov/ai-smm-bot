"""Модель готовности площадки к реальной автопубликации — v0.5.9.

Хранит readiness по каждой площадке проекта (Telegram/VK/Instagram/MAX/OK — у каждой свои
требования). Это НЕ включатель live: реальная публикация по-прежнему требует глобальных
``*_LIVE_PUBLISHING_ENABLED`` флагов. ``platform_live_enabled`` — per-project/per-platform
переключатель, который НЕ обходит глобальные флаги.

БЕЗОПАСНОСТЬ:
- секретов/сырых токенов не хранит (только признак наличия);
- не заменяет и не обходит глобальные live-флаги.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# Площадки и их поддержка live-публикации (для «скоро» / unsupported в readiness).
LIVE_READINESS_PLATFORMS: tuple[str, ...] = ("telegram", "vk", "instagram", "max", "ok")
LIVE_READINESS_LIVE_CAPABLE_PLATFORMS: tuple[str, ...] = ("telegram", "vk", "instagram")


class PlatformLiveReadiness(Base, TimestampMixin):
    """Готовность конкретной площадки проекта к реальной автопубликации."""

    __tablename__ = "platform_live_readiness"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    status: Mapped[str] = mapped_column(
        String(16), index=True, default="not_checked", nullable=False
    )
    platform_live_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    credentials_present: Mapped[bool] = mapped_column(default=False, nullable=False)
    credentials_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    last_probe_status: Mapped[str | None] = mapped_column(String(16), default=None)
    last_probe_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )
    readiness_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    required_fields: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    missing_fields: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    media_requirements: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    confirmation_required: Mapped[bool] = mapped_column(default=True, nullable=False)

    confirmed_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    disabled_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    readiness_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
