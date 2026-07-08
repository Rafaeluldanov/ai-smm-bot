"""Репозиторий биллинга: счёт, журнал операций, usage-события, тарифы."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import BillingAccount, BillingLedgerEntry, TariffPlan, UsageEvent

# --- Billing account ---


def get_billing_account_by_account_id(db: Session, account_id: int) -> BillingAccount | None:
    """Вернуть биллинг-счёт аккаунта или None."""
    return db.scalars(select(BillingAccount).where(BillingAccount.account_id == account_id)).first()


def create_billing_account(
    db: Session, account_id: int, tariff_plan_slug: str | None = None, balance_units: int = 0
) -> BillingAccount:
    """Создать биллинг-счёт аккаунта."""
    billing = BillingAccount(
        account_id=account_id,
        balance_units=balance_units,
        currency="RUB",
        tariff_plan_slug=tariff_plan_slug,
        status="active",
    )
    db.add(billing)
    db.commit()
    db.refresh(billing)
    return billing


def set_balance(db: Session, billing: BillingAccount, balance_units: int) -> BillingAccount:
    """Установить баланс счёта (после операции)."""
    billing.balance_units = balance_units
    db.commit()
    db.refresh(billing)
    return billing


# --- Ledger ---


def get_ledger_by_idempotency_key(db: Session, key: str) -> BillingLedgerEntry | None:
    """Вернуть запись журнала по idempotency_key или None."""
    return db.scalars(
        select(BillingLedgerEntry).where(BillingLedgerEntry.idempotency_key == key)
    ).first()


def create_ledger_entry(
    db: Session,
    billing_account_id: int,
    entry_type: str,
    amount_units: int,
    balance_after_units: int,
    description: str = "",
    idempotency_key: str | None = None,
    entry_metadata: dict[str, Any] | None = None,
) -> BillingLedgerEntry:
    """Создать запись журнала биллинга."""
    entry = BillingLedgerEntry(
        billing_account_id=billing_account_id,
        entry_type=entry_type,
        amount_units=amount_units,
        balance_after_units=balance_after_units,
        description=description,
        idempotency_key=idempotency_key,
        entry_metadata=entry_metadata or {},
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def list_ledger(db: Session, billing_account_id: int, limit: int = 100) -> list[BillingLedgerEntry]:
    """Вернуть журнал операций счёта (свежие первыми)."""
    stmt = (
        select(BillingLedgerEntry)
        .where(BillingLedgerEntry.billing_account_id == billing_account_id)
        .order_by(BillingLedgerEntry.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


# --- Usage events ---


def create_usage_event(
    db: Session,
    account_id: int,
    event_type: str,
    units: int,
    project_id: int | None = None,
    post_id: int | None = None,
    provider_cost_estimate: int | None = None,
    markup_percent: int | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> UsageEvent:
    """Создать usage-событие."""
    event = UsageEvent(
        account_id=account_id,
        project_id=project_id,
        post_id=post_id,
        event_type=event_type,
        units=units,
        provider_cost_estimate=provider_cost_estimate,
        markup_percent=markup_percent,
        event_metadata=event_metadata or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def list_usage_events(db: Session, account_id: int, limit: int = 100) -> list[UsageEvent]:
    """Вернуть usage-события аккаунта (свежие первыми)."""
    stmt = (
        select(UsageEvent)
        .where(UsageEvent.account_id == account_id)
        .order_by(UsageEvent.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


# --- Tariffs ---


def get_tariff_by_slug(db: Session, slug: str) -> TariffPlan | None:
    """Вернуть тариф по slug или None."""
    return db.scalars(select(TariffPlan).where(TariffPlan.slug == slug)).first()


def create_tariff(
    db: Session,
    slug: str,
    name: str,
    included_units: int = 0,
    unit_price_rub: int = 0,
    markup_percent: int = 0,
) -> TariffPlan:
    """Создать тарифный план."""
    tariff = TariffPlan(
        slug=slug,
        name=name,
        included_units=included_units,
        unit_price_rub=unit_price_rub,
        markup_percent=markup_percent,
        status="active",
    )
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    return tariff


def list_tariffs(db: Session) -> list[TariffPlan]:
    """Вернуть все тарифы."""
    return list(db.scalars(select(TariffPlan).order_by(TariffPlan.id)).all())
