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

# Статусы счёта (PaymentInvoice): draft → pending → paid | canceled | failed | expired.
STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_CANCELED = "canceled"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

# Публичные алиасы статусов счёта (единое именование v0.3.4).
PAYMENT_STATUS_DRAFT = STATUS_DRAFT
PAYMENT_STATUS_PENDING = STATUS_PENDING
PAYMENT_STATUS_PAID = STATUS_PAID
PAYMENT_STATUS_CANCELED = STATUS_CANCELED
PAYMENT_STATUS_FAILED = STATUS_FAILED
PAYMENT_STATUS_EXPIRED = STATUS_EXPIRED

INVOICE_STATUSES: tuple[str, ...] = (
    STATUS_DRAFT,
    STATUS_PENDING,
    STATUS_PAID,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_EXPIRED,
)
# Терминальные статусы неуспешного счёта (оплатить нельзя).
INVOICE_UNPAID_TERMINAL: tuple[str, ...] = (STATUS_CANCELED, STATUS_FAILED, STATUS_EXPIRED)

# Статусы транзакции (PaymentTransaction).
TX_STATUS_PENDING = "pending"
TX_STATUS_SUCCEEDED = "succeeded"
TX_STATUS_FAILED = "failed"
TX_STATUS_CANCELED = "canceled"
TX_STATUS_REFUNDED = "refunded"
TRANSACTION_STATUSES: tuple[str, ...] = (
    TX_STATUS_PENDING,
    TX_STATUS_SUCCEEDED,
    TX_STATUS_FAILED,
    TX_STATUS_CANCELED,
    TX_STATUS_REFUNDED,
)

# Статусы записи журнала вебхуков (PaymentWebhookLog.status).
WEBHOOK_STATUS_RECEIVED = "received"
WEBHOOK_STATUS_PROCESSED = "processed"
WEBHOOK_STATUS_IGNORED = "ignored"
WEBHOOK_STATUS_FAILED = "failed"
WEBHOOK_STATUSES: tuple[str, ...] = (
    WEBHOOK_STATUS_RECEIVED,
    WEBHOOK_STATUS_PROCESSED,
    WEBHOOK_STATUS_IGNORED,
    WEBHOOK_STATUS_FAILED,
)

# Публичные алиасы методов оплаты (единое именование v0.3.4).
PAYMENT_METHOD_BANK_CARD = METHOD_BANK_CARD
PAYMENT_METHOD_SBP = METHOD_SBP
PAYMENT_METHOD_QR = METHOD_QR
PAYMENT_METHOD_INVOICE_IP = METHOD_INVOICE_IP
PAYMENT_METHOD_INVOICE_COMPANY = METHOD_INVOICE_COMPANY
PAYMENT_METHOD_MANUAL_ADMIN = METHOD_MANUAL_ADMIN
# Методы, формирующие QR-payload (СБП/QR).
QR_METHODS: tuple[str, ...] = (METHOD_SBP, METHOD_QR)
# Методы «счёт по реквизитам» (ИП/ООО).
INVOICE_METHODS: tuple[str, ...] = (METHOD_INVOICE_IP, METHOD_INVOICE_COMPANY)


class PaymentProviderError(Exception):
    """Ошибка платёжного провайдера (метод не поддержан, live выключен и т. п.)."""


class WebhookSignatureError(PaymentProviderError):
    """Подпись вебхука не подтверждена (в production → HTTP 403)."""


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
    # Идентификатор события провайдера (для идемпотентности; дубликаты игнорируются).
    provider_event_id: str | None = None


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
