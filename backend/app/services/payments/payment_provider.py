"""Интерфейс платёжного провайдера и общие типы результата.

Провайдеры НЕ хранят секреты в результатах и НЕ логируют ключи. На этом этапе сеть
не вызывается: mock создаёт fake invoice, остальные — sandbox/planned-скелеты.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

# Методы оплаты (Россия).
METHOD_BANK_CARD = "bank_card"
METHOD_SBP = "sbp"
METHOD_QR = "qr"
METHOD_INVOICE_IP = "invoice_for_ip"
METHOD_INVOICE_COMPANY = "invoice_for_company"
METHOD_MANUAL_ADMIN = "manual_admin_topup"

PAYMENT_METHODS: tuple[str, ...] = (
    METHOD_BANK_CARD,
    METHOD_SBP,
    METHOD_QR,
    METHOD_INVOICE_IP,
    METHOD_INVOICE_COMPANY,
    METHOD_MANUAL_ADMIN,
)

# Статусы платежа.
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"


class PaymentProviderError(Exception):
    """Ошибка платёжного провайдера (метод не поддержан, live выключен и т. п.)."""


@dataclass(frozen=True)
class PaymentInvoiceResult:
    """Результат создания счёта у провайдера (без секретов)."""

    provider: str
    provider_payment_id: str
    status: str
    payment_url: str | None = None
    qr_payload: str | None = None
    amount_rub: int = 0
    sandbox: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentStatusResult:
    """Статус платежа у провайдера."""

    provider: str
    provider_payment_id: str
    status: str


@dataclass(frozen=True)
class PaymentWebhookResult:
    """Разобранный вебхук провайдера (санитизированный)."""

    provider: str
    event_type: str
    provider_payment_id: str | None
    status: str
    signature_valid: bool
    payload_sanitized: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaymentRefundResult:
    """Результат возврата (planned/optional)."""

    provider: str
    provider_payment_id: str
    status: str
    amount_rub: int = 0


class PaymentProvider(Protocol):
    """Контракт платёжного провайдера. Реализации не делают сетевых вызовов сейчас."""

    name: str
    live_supported: bool

    def create_invoice(
        self,
        account_id: int,
        amount_units: int,
        amount_rub: int,
        method: str,
        customer: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentInvoiceResult: ...

    def get_payment_status(self, provider_payment_id: str) -> PaymentStatusResult: ...

    def handle_webhook(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> PaymentWebhookResult: ...
