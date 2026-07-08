"""Модели биллинга: депозит (units), журнал операций, usage-события, тарифы.

Единица учёта — внутренние ``units`` (условные токены). Реальных платежей на этом
этапе нет: пополнение — только ручное (manual_topup) через fake-провайдер.
Идемпотентность операций — по ``idempotency_key`` (уникальный).
"""

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class TariffPlan(Base, TimestampMixin):
    """Тарифный план: включённые units, цена unit, наценка."""

    __tablename__ = "tariff_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    included_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Цена одной единицы в рублях (для оценок; реальных платежей нет).
    unit_price_rub: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    markup_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # active | archived
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)


class BillingAccount(Base, TimestampMixin):
    """Биллинг-счёт аккаунта: баланс в units. Один на аккаунт."""

    __tablename__ = "billing_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    balance_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    tariff_plan_slug: Mapped[str | None] = mapped_column(String(64), default=None)
    # active | suspended
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)


class BillingLedgerEntry(Base, TimestampMixin):
    """Запись журнала биллинга (пополнение/списание/возврат/корректировка)."""

    __tablename__ = "billing_ledger_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_billing_ledger_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    billing_account_id: Mapped[int] = mapped_column(
        ForeignKey("billing_accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # topup | debit | refund | adjustment
    entry_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Знаковая величина в units (topup/refund > 0, debit < 0).
    amount_units: Mapped[int] = mapped_column(Integer, nullable=False)
    balance_after_units: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), default=None)
    entry_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)


class UsageEvent(Base, TimestampMixin):
    """Событие потребления ресурсов (генерация, подбор медиа, публикация и т. п.)."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    post_id: Mapped[int | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), index=True, default=None
    )
    # ai_generation | media_selection | image_processing | publication_preview |
    # publication_live | analytics
    event_type: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider_cost_estimate: Mapped[int | None] = mapped_column(Integer, default=None)
    markup_percent: Mapped[int | None] = mapped_column(Integer, default=None)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
