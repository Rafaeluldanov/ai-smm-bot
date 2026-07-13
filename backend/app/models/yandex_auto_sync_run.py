"""Модель прогона авто-синхронизации Яндекс Диска — v0.5.7.

История синхронизаций: когда проверяли Диск, сколько файлов увидели/импортировали, что пошло не
так. Показывается клиенту как «когда последний раз проверяли диск». Секретов/сырых путей не хранит;
``public_url`` — только маской; реальной сети/публикаций/удаления файлов нет.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.7, Часть 1). --- #
YANDEX_AUTO_SYNC_RUN_STATUSES: tuple[str, ...] = (
    "preview",
    "started",
    "synced",
    "partially_synced",
    "skipped",
    "failed",
    "blocked",
)


class YandexAutoSyncRun(Base, TimestampMixin):
    """Один прогон авто-синхронизации Яндекс Диска (preview/dry-run/реальный за флагами)."""

    __tablename__ = "yandex_auto_sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sync_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_yandex_sync_profiles.id", ondelete="SET NULL"), index=True, default=None
    )
    autopilot_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_autopilot_profiles.id", ondelete="SET NULL"), default=None
    )

    status: Mapped[str] = mapped_column(String(24), index=True, default="preview", nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), default="public_disk_url", nullable=False)
    public_url_masked: Mapped[str | None] = mapped_column(String(255), default=None)
    root_folder: Mapped[str | None] = mapped_column(String(255), default=None)
    dry_run: Mapped[bool] = mapped_column(Boolean, index=True, default=True, nullable=False)

    files_seen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    files_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    media_assets_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    media_assets_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quality_snapshots_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    fingerprints_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    curation_tasks_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(512), default=None)
    run_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, default=None)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_by_worker_owner_id: Mapped[str | None] = mapped_column(String(128), default=None)
