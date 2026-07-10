"""REST API биллинга (депозит в units, журнал, usage, оценка стоимости).

Реальных платежей нет: пополнение — ручное (fake-провайдер). Идемпотентность — по
``idempotency_key``. При недостатке баланса действие не выполняется (см.
:class:`BillingService`).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_billing_service, get_db, get_payment_service
from app.repositories import payment_repository
from app.schemas.billing import (
    BillingBalanceRead,
    EstimateRequest,
    EstimateResult,
    LedgerEntryRead,
    TopupRequest,
    UsageEventRead,
)
from app.schemas.payment import (
    BillingProfileRead,
    BillingProfileUpsert,
    InvoiceCreateRequest,
    InvoiceRead,
    TopupPreviewRequest,
    TopupPreviewResult,
    WebhookResult,
)
from app.services.billing_service import BillingError, BillingService
from app.services.payments.payment_provider import PaymentProviderError
from app.services.payments.payment_service import PaymentService

router = APIRouter(prefix="/billing", tags=["billing"])

DbSession = Annotated[Session, Depends(get_db)]
BillingSvc = Annotated[BillingService, Depends(get_billing_service)]
PaymentSvc = Annotated[PaymentService, Depends(get_payment_service)]


def _payments(action: Any) -> Any:
    """Привести ошибки платёжного слоя к HTTP 400."""
    try:
        return action()
    except PaymentProviderError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/account/{account_id}/balance", response_model=BillingBalanceRead)
def get_balance(account_id: int, db: DbSession, service: BillingSvc) -> BillingBalanceRead:
    """Баланс биллинг-счёта аккаунта (создаётся при первом обращении)."""
    return BillingBalanceRead.model_validate(service.get_balance(db, account_id))


@router.post("/account/{account_id}/manual-topup", response_model=LedgerEntryRead)
def manual_topup(
    account_id: int, payload: TopupRequest, db: DbSession, service: BillingSvc
) -> LedgerEntryRead:
    """Ручное пополнение депозита (fake). Идемпотентно по ключу."""
    try:
        entry = service.manual_topup(
            db, account_id, payload.amount_units, payload.idempotency_key, payload.description
        )
    except BillingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return LedgerEntryRead.model_validate(entry)


@router.get("/account/{account_id}/ledger", response_model=list[LedgerEntryRead])
def get_ledger(account_id: int, db: DbSession, service: BillingSvc) -> list[LedgerEntryRead]:
    """Журнал операций счёта (свежие первыми)."""
    return [LedgerEntryRead.model_validate(e) for e in service.list_ledger(db, account_id)]


@router.get("/account/{account_id}/usage-events", response_model=list[UsageEventRead])
def get_usage_events(account_id: int, db: DbSession, service: BillingSvc) -> list[UsageEventRead]:
    """Usage-события аккаунта (свежие первыми)."""
    return [UsageEventRead.model_validate(e) for e in service.list_usage(db, account_id)]


@router.post("/estimate", response_model=EstimateResult)
def estimate(payload: EstimateRequest, db: DbSession, service: BillingSvc) -> EstimateResult:
    """Оценить стоимость действия в units (и доступность при заданном account_id)."""
    units = service.estimate_action_cost(payload.action_type, payload.payload)
    balance: int | None = None
    affordable: bool | None = None
    if payload.account_id is not None:
        billing = service.get_balance(db, payload.account_id)
        balance = billing.balance_units
        affordable = billing.balance_units >= units
    return EstimateResult(
        action_type=payload.action_type,
        estimated_units=units,
        balance_units=balance,
        affordable=affordable,
    )


# --- Платежи (Россия): счета, mock-оплата, вебхуки, профиль ---
# Реальные платежи выключены (PAYMENTS_LIVE_ENABLED=false): счета — mock/sandbox,
# баланс пополняется только после paid (mock-pay/webhook), идемпотентно.


@router.get("/providers")
def list_providers(payments: PaymentSvc) -> list[dict[str, Any]]:
    """Список платёжных провайдеров и их доступность (mock/sandbox/live)."""
    return payments.available_providers()


@router.post("/account/{account_id}/topup/preview", response_model=TopupPreviewResult)
def topup_preview(
    account_id: int, payload: TopupPreviewRequest, payments: PaymentSvc
) -> TopupPreviewResult:
    """Оценка пополнения (units → рубли), без создания счёта. Бесплатно."""
    data = payments.topup_preview(
        account_id, payload.amount_units, payload.method, payload.provider
    )
    return TopupPreviewResult(**data)


@router.post("/account/{account_id}/invoices", response_model=InvoiceRead)
def create_invoice(
    account_id: int, payload: InvoiceCreateRequest, db: DbSession, payments: PaymentSvc
) -> InvoiceRead:
    """Создать счёт на пополнение. Баланс НЕ меняется до оплаты."""
    customer = payload.customer.model_dump() if payload.customer is not None else None
    invoice = _payments(
        lambda: payments.create_invoice(
            db,
            account_id,
            payload.amount_units,
            method=payload.method,
            provider=payload.provider,
            customer=customer,
            idempotency_key=payload.idempotency_key,
        )
    )
    return InvoiceRead.model_validate(invoice)


@router.get("/account/{account_id}/invoices", response_model=list[InvoiceRead])
def list_invoices(account_id: int, db: DbSession, payments: PaymentSvc) -> list[InvoiceRead]:
    """Счета аккаунта (свежие первыми)."""
    return [InvoiceRead.model_validate(i) for i in payments.list_invoices(db, account_id)]


@router.get("/invoices/{invoice_id}", response_model=InvoiceRead)
def get_invoice(invoice_id: int, db: DbSession, payments: PaymentSvc) -> InvoiceRead:
    """Получить счёт по id (404 — если нет)."""
    invoice = payments.get_invoice(db, invoice_id)
    if invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Счёт не найден")
    return InvoiceRead.model_validate(invoice)


@router.post("/invoices/{invoice_id}/mock-pay", response_model=InvoiceRead)
def mock_pay(invoice_id: int, db: DbSession, payments: PaymentSvc) -> InvoiceRead:
    """Подтвердить mock-оплату счёта: paid + пополнение баланса (идемпотентно)."""
    invoice = _payments(lambda: payments.mock_pay(db, invoice_id))
    return InvoiceRead.model_validate(invoice)


@router.post("/webhooks/{provider}", response_model=WebhookResult)
def payment_webhook(
    provider: str,
    db: DbSession,
    payments: PaymentSvc,
    payload: Annotated[dict[str, Any], Body()],
) -> WebhookResult:
    """Вебхук провайдера: логируется, проверяется, идемпотентно пополняет баланс."""
    result = _payments(lambda: payments.handle_webhook(db, provider, payload))
    return WebhookResult(**result)


@router.get("/account/{account_id}/profile", response_model=BillingProfileRead | None)
def get_billing_profile(account_id: int, db: DbSession) -> BillingProfileRead | None:
    """Реквизиты плательщика аккаунта (физлицо/ИП/ООО) или null."""
    profile = payment_repository.get_profile_by_account(db, account_id)
    return BillingProfileRead.model_validate(profile) if profile is not None else None


@router.put("/account/{account_id}/profile", response_model=BillingProfileRead)
def upsert_billing_profile(
    account_id: int, payload: BillingProfileUpsert, db: DbSession
) -> BillingProfileRead:
    """Создать/обновить реквизиты плательщика (без секретов платежей)."""
    profile = payment_repository.upsert_profile(db, account_id, payload.model_dump())
    return BillingProfileRead.model_validate(profile)
