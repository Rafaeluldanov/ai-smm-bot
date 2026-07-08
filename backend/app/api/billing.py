"""REST API биллинга (депозит в units, журнал, usage, оценка стоимости).

Реальных платежей нет: пополнение — ручное (fake-провайдер). Идемпотентность — по
``idempotency_key``. При недостатке баланса действие не выполняется (см.
:class:`BillingService`).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_billing_service, get_db
from app.schemas.billing import (
    BillingBalanceRead,
    EstimateRequest,
    EstimateResult,
    LedgerEntryRead,
    TopupRequest,
    UsageEventRead,
)
from app.services.billing_service import BillingError, BillingService

router = APIRouter(prefix="/billing", tags=["billing"])

DbSession = Annotated[Session, Depends(get_db)]
BillingSvc = Annotated[BillingService, Depends(get_billing_service)]


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
