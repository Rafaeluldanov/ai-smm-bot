"""Модель профиля авто-синхронизации Яндекс Диска — v0.5.7.

Клиент загружает картинки в папку Яндекс Диска — Botfleet сам находит новые файлы и готовит
медиатеку для автопостинга (sync → базовые теги → quality scoring → fingerprint/dedup → curation
preview). Профиль — простой клиентский слой поверх существующих CrmSmmResource / media source.

БЕЗОПАСНОСТЬ:
- секретов/сырых токенов не хранит; ``public_url`` — публичная ссылка (не секрет), но наружу
  отдаётся маской;
- ``project_id`` уникален (один профиль синхронизации на проект);
- реальной сети/публикаций нет; файлы не удаляются.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.7, Часть 1). --- #
YANDEX_AUTO_SYNC_STATUSES: tuple[str, ...] = (
    "disabled",
    "ready",
    "running",
    "paused",
    "blocked",
    "failed",
)
YANDEX_AUTO_SYNC_SOURCE_TYPES: tuple[str, ...] = (
    "public_disk_url",
    "oauth_disk_later",
    "manual_upload_later",
)
YANDEX_AUTO_SYNC_BLOCKER_TYPES: tuple[str, ...] = (
    "no_yandex_disk",
    "invalid_public_url",
    "no_media_found",
    "too_few_media",
    "sync_disabled",
    "network_disabled",
    "credentials_missing",
    "rate_limited",
    "unsupported_folder",
    "safety_gate_failed",
)
YANDEX_AUTO_SYNC_ACTIONS: tuple[str, ...] = (
    "preview",
    "sync_now",
    "sync_worker_tick",
    "pause",
    "resume",
    "refresh_status",
)


class ProjectYandexSyncProfile(Base, TimestampMixin):
    """Профиль авто-синхронизации Яндекс Диска проекта (одна панель на проект)."""

    __tablename__ = "project_yandex_sync_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    autopilot_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_autopilot_profiles.id", ondelete="SET NULL"), index=True, default=None
    )

    status: Mapped[str] = mapped_column(String(16), index=True, default="ready", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, index=True, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), default="public_disk_url", nullable=False)

    public_url: Mapped[str | None] = mapped_column(Text, default=None)
    root_folder: Mapped[str | None] = mapped_column(String(255), default=None)
    default_tags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    allowed_folders: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    sync_frequency_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_sync_status: Mapped[str | None] = mapped_column(String(24), default=None)
    last_sync_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    next_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )

    media_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    video_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_media_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_media_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_media_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    active_blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    profile_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
