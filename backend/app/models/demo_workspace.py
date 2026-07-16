"""Demo-воркспейс (v0.9.0) — контейнер тестового окружения AI Business OS MVP.

Хранит демонстрационную «компанию» (название/отрасль/описание) для E2E-прогонов сценариев. Это
тестовая сущность demo-режима: реальных пользователей/CRM/платежей не создаёт.

БЕЗОПАСНОСТЬ:
- demo-воркспейс — только тестовый контейнер; секретов не содержит; внешних действий не выполняет.
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DemoWorkspace(Base, TimestampMixin):
    """Demo-воркспейс E2E-тестирования (per-account, без секретов)."""

    __tablename__ = "demo_workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    industry: Mapped[str] = mapped_column(String(100), default="", nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
