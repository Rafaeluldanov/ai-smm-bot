"""Pydantic-схемы платежей (профиль плательщика, счета, транзакции, вебхуки).

Секреты провайдеров сюда НЕ попадают. Суммы — в units и в рублях (оценка).
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Методы оплаты (для России).
PAYMENT_METHODS: tuple[str, ...] = (
    "bank_card",
    "sbp",
    "qr",
    "invoice_for_ip",
    "invoice_for_company",
    "manual_admin_topup",
)
CUSTOMER_TYPES: tuple[str, ...] = ("individual", "ip", "company")


class BillingProfileBase(BaseModel):
    """Реквизиты плательщика (физлицо / ИП / ООО)."""

    customer_type: str = "individual"
    legal_name: str | None = None
    inn: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    ogrnip: str | None = None
    legal_address: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None


class BillingProfileUpsert(BillingProfileBase):
    """Данные для создания/обновления профиля плательщика."""


class BillingProfileRead(BillingProfileBase):
    """Профиль плательщика в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    status: str
    created_at: datetime
    updated_at: datetime


class InvoiceCreateRequest(BaseModel):
    """Запрос на создание счёта (пополнение units)."""

    amount_units: int = Field(gt=0)
    method: str = "bank_card"
    provider: str | None = None  # None → провайдер по умолчанию из конфига
    idempotency_key: str | None = None
    customer: BillingProfileBase | None = None


class InvoiceRead(BaseModel):
    """Счёт на пополнение."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    provider: str
    method: str
    amount_units: int
    amount_rub: int
    status: str
    payment_url: str | None = None
    qr_payload: str | None = None
    provider_payment_id: str | None = None
    idempotency_key: str | None = None
    invoice_metadata: dict[str, Any] = Field(default_factory=dict)
    paid_at: datetime | None = None
    created_at: datetime


class TransactionRead(BaseModel):
    """Транзакция по счёту (санитизированная)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    invoice_id: int
    account_id: int
    provider: str
    provider_payment_id: str | None = None
    status: str
    amount_units: int
    amount_rub: int
    created_at: datetime


class TopupPreviewRequest(BaseModel):
    """Оценка пополнения: units → рубли, метод, провайдер."""

    amount_units: int = Field(gt=0)
    method: str = "bank_card"
    provider: str | None = None


class TopupPreviewResult(BaseModel):
    """Результат оценки пополнения (без создания счёта)."""

    amount_units: int
    amount_rub: int
    method: str
    provider: str
    payments_live_enabled: bool
    note: str


class WebhookResult(BaseModel):
    """Результат обработки вебхука провайдера."""

    provider: str
    accepted: bool
    processed: bool
    duplicate: bool = False
    invoice_id: int | None = None
    message: str = ""
