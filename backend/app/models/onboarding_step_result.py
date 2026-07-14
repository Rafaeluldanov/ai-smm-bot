"""Модель результата шага клиентского онбординга — v0.6.4.

Журнал по каждому шагу мастера (started/completed/failed) с безопасными input/output. Не хранит
токенов/секретов/сырых payload — только безопасные данные шага.
"""

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

ONBOARDING_STEP_STATUSES: tuple[str, ...] = ("started", "completed", "failed")


class OnboardingStepResult(Base, TimestampMixin):
    """Результат одного шага онбординга (безопасный, без секретов)."""

    __tablename__ = "onboarding_step_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("onboarding_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_name: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="started", nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    output_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
