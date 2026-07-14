"""Модель runbook первого production Telegram-канала — v0.6.3.

Клиентский «запуск Telegram автопилота»: агрегирует готовность (канал/media proxy/календарь/
баланс/live readiness/мониторинг), даёт чек-лист и управляет ручным production-тестом. Runbook НЕ
включает live сам — реальная отправка возможна только через существующие safety-gates.

БЕЗОПАСНОСТЬ:
- НЕ хранит токены/секреты/сырые payload — только безопасные агрегаты и метаданные;
- глобальные live-флаги не трогает.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.3) --- #
TELEGRAM_LIVE_RUNBOOK_STATUSES: tuple[str, ...] = (
    "draft",
    "ready",
    "blocked",
    "enabled",
    "paused",
)


class TelegramLiveRunbook(Base, TimestampMixin):
    """Runbook запуска Telegram-канала проекта (готовность + production-тест)."""

    __tablename__ = "telegram_live_runbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    project_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(16), index=True, default="draft", nullable=False)

    channel_id: Mapped[str | None] = mapped_column(String(128), default=None)
    channel_name: Mapped[str | None] = mapped_column(String(255), default=None)

    connected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    media_proxy_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    calendar_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    readiness_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monitoring_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    balance_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    checklist: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    blockers: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    warnings: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
