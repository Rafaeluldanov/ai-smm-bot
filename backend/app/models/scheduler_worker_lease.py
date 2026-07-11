"""Модель lease (аренды) фонового scheduler-worker.

Простой DB-based lock/lease (без Redis/Celery на MVP): гарантирует, что в один момент
активен один worker. Если процесс умер — lease истекает по TTL и может быть перехвачен.

БЕЗОПАСНОСТЬ: ``lease_metadata`` НЕ содержит секретов/токенов (только owner/host/pid).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class SchedulerWorkerLease(Base, TimestampMixin):
    """Аренда исполнения фонового worker-а (одна активная на ключ)."""

    __tablename__ = "scheduler_worker_leases"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Ключ ресурса (например «scheduler-worker») — уникален.
    lease_key: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    # Идентификатор владельца (host:pid:suffix). Секретов не содержит.
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # active | released | expired
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    acquired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, default=None
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    lease_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
