"""Назначение владельца оптимизации (v0.8.2) — история ответственности.

Фиксирует, кто и в какой роли отвечает за governance-запись, с интервалом assigned_at..released_at.
Только запись ответственности — задач не выполняет, бизнес не меняет.

БЕЗОПАСНОСТЬ:
- назначение — только фиксация владельца; секретов не содержит.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OptimizationOwnerAssignment(Base):
    """Назначение владельца governance-записи (история, без секретов)."""

    __tablename__ = "optimization_owner_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    governance_id: Mapped[int] = mapped_column(
        ForeignKey("optimization_governances.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    # Роль ответственного (owner | reviewer | contributor).
    role: Mapped[str] = mapped_column(String(30), default="owner", nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
