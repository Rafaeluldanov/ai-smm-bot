"""Модели платежей (архитектура для России): профиль, счета, транзакции, вебхуки.

РЕАЛЬНЫХ платежей нет: без ``PAYMENTS_LIVE_ENABLED=true`` все счета создаются как
mock/sandbox. Баланс пополняется только после статуса ``paid`` (mock-pay/webhook).
Секреты провайдеров в БД НЕ хранятся; ``*_sanitized`` payload очищается от ключей.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class BillingProfile(Base, TimestampMixin):
    """Реквизиты плательщика аккаунта: физлицо / ИП / ООО."""

    __tablename__ = "billing_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # individual | ip | company
    customer_type: Mapped[str] = mapped_column(String(20), default="individual", nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(500), default=None)
    inn: Mapped[str | None] = mapped_column(String(20), default=None)
    kpp: Mapped[str | None] = mapped_column(String(20), default=None)
    ogrn: Mapped[str | None] = mapped_column(String(20), default=None)
    ogrnip: Mapped[str | None] = mapped_column(String(20), default=None)
    legal_address: Mapped[str | None] = mapped_column(String(1000), default=None)
    contact_name: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    phone: Mapped[str | None] = mapped_column(String(40), default=None)
    # active | archived
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)


class PaymentInvoice(Base, TimestampMixin):
    """Счёт на пополнение units. Создание счёта НЕ меняет баланс."""

    __tablename__ = "payment_invoices"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_payment_invoice_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # mock | yookassa | tbank | cloudpayments | robokassa | ...
    provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # bank_card | sbp | qr | invoice_for_ip | invoice_for_company | manual_admin_topup
    method: Mapped[str] = mapped_column(String(40), nullable=False)
    amount_units: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_rub: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # draft | pending | paid | canceled | failed | expired
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True, nullable=False)
    payment_url: Mapped[str | None] = mapped_column(String(1024), default=None)
    qr_payload: Mapped[str | None] = mapped_column(String(1024), default=None)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), default=None)
    invoice_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class PaymentTransaction(Base, TimestampMixin):
    """Транзакция по счёту (санитизированная копия ответа провайдера)."""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("payment_invoices.id", ondelete="CASCADE"), index=True, nullable=False
    )
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_units: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    amount_rub: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    raw_payload_sanitized: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )


class PaymentWebhookLog(Base, TimestampMixin):
    """Журнал входящих вебхуков провайдеров (санитизированный, без секретов)."""

    __tablename__ = "payment_webhook_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(255), index=True, default=None)
    payload_sanitized: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
