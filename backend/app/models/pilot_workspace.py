"""Pilot-воркспейс (v0.9.1) — окружение первого реального бизнес-пилота.

Контейнер пилота реальной компании (название/отрасль/статус/создатель). Всё внутри — только
advisory: бизнес не меняется, CRM/workflow/внешние действия не выполняются.

БЕЗОПАСНОСТЬ:
- pilot-воркспейс — только контейнер пилота; секретов не содержит; внешних действий не выполняет.
"""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin

# Статус пилота.
PILOT_STATUSES: tuple[str, ...] = ("draft", "active", "paused", "completed")


class PilotWorkspace(Base, TimestampMixin):
    """Pilot-воркспейс (per-account, без секретов)."""

    __tablename__ = "pilot_workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    industry: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    # draft | active | paused | completed
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
