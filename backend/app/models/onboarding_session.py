"""Модель клиентского онбординга (первый запуск автопилота за 5 минут) — v0.6.4.

Ведёт клиента по 5 шагам (бизнес → материалы → площадки → цель → запуск). Скрывает от клиента
worker/миграции/токены/live-флаги/готовность/биллинг. После онбординга система READY, но LIVE=OFF.

БЕЗОПАСНОСТЬ: не хранит токенов/секретов — только безопасные ответы шагов; live не включает.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.6.4) --- #
ONBOARDING_STATUSES: tuple[str, ...] = (
    "started",
    "business_completed",
    "media_completed",
    "platforms_completed",
    "goal_completed",
    "ready",
    "completed",
    "paused",
)
ONBOARDING_GOALS: tuple[str, ...] = ("sales", "brand", "reach", "expertise")
ONBOARDING_FREQUENCIES: tuple[str, ...] = ("daily", "3_week", "weekly")


class OnboardingSession(Base, TimestampMixin):
    """Сессия клиентского онбординга (одна активная на клиента)."""

    __tablename__ = "onboarding_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(24), index=True, default="started", nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    business_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    media_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    platform_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    goal_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    completion_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
