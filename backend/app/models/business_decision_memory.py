"""Память решений владельца (v0.7.1) — долговременный контекст AI Chief of Staff.

Ассистент запоминает решения/предпочтения/ограничения владельца («не использовать
агрессивные продажи», «фокус на кейсах», «Telegram — главный канал») и подмешивает их
контекстом в будущие AI-рекомендации (Learning / Content Strategy / Campaign Manager).

БЕЗОПАСНОСТЬ:
- строго per-project; секретов НЕТ; память лишь ДОБАВЛЯЕТ контекст рекомендациям,
  НЕ меняет бизнес/CRM/бюджет/продажи напрямую.
"""

from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# Максимальная длина семантического ключа решения — единый источник (service/repo сверяются).
KEY_MAX_LENGTH = 80


class BusinessDecisionMemory(Base, TimestampMixin):
    """Одно запомненное решение владельца (per-project, без секретов)."""

    __tablename__ = "business_decision_memories"
    __table_args__ = (
        Index("ix_business_decision_memories_project_active", "project_id", "active"),
        Index("ix_business_decision_memories_account", "account_id"),
        # Одна АКТИВНАЯ запись на (project_id, key) — на уровне БД (в т. ч. против гонок).
        Index(
            "uq_business_decision_active_key",
            "project_id",
            "key",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # preference | strategy | restriction | approval
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # семантический ключ (напр. sales_style / main_channel / content_focus)
    key: Mapped[str] = mapped_column(String(KEY_MAX_LENGTH), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    active: Mapped[bool] = mapped_column(default=True, nullable=False)
