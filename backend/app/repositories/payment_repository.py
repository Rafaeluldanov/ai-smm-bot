"""Репозиторий платежей: профиль плательщика, счета, транзакции, вебхуки."""

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment import (
    BillingProfile,
    PaymentInvoice,
    PaymentTransaction,
    PaymentWebhookLog,
)

# --- Billing profile ---


def get_profile_by_account(db: Session, account_id: int) -> BillingProfile | None:
    """Вернуть профиль плательщика аккаунта или None."""
    return db.scalars(select(BillingProfile).where(BillingProfile.account_id == account_id)).first()


def upsert_profile(db: Session, account_id: int, fields: dict[str, Any]) -> BillingProfile:
    """Создать/обновить профиль плательщика аккаунта."""
    profile = get_profile_by_account(db, account_id)
    if profile is None:
        profile = BillingProfile(account_id=account_id, status="active")
        db.add(profile)
    for key, value in fields.items():
        if hasattr(profile, key) and value is not None:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# --- Invoices ---


def create_invoice(db: Session, **fields: Any) -> PaymentInvoice:
    """Создать счёт на пополнение."""
    invoice = PaymentInvoice(**fields)
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return invoice


def get_invoice(db: Session, invoice_id: int) -> PaymentInvoice | None:
    """Вернуть счёт по id или None."""
    return db.get(PaymentInvoice, invoice_id)


def get_invoice_by_idempotency_key(db: Session, key: str) -> PaymentInvoice | None:
    """Вернуть счёт по idempotency_key или None."""
    return db.scalars(select(PaymentInvoice).where(PaymentInvoice.idempotency_key == key)).first()


def get_invoice_by_provider_payment_id(
    db: Session, provider: str, provider_payment_id: str
) -> PaymentInvoice | None:
    """Вернуть счёт по (provider, provider_payment_id) или None."""
    return db.scalars(
        select(PaymentInvoice).where(
            PaymentInvoice.provider == provider,
            PaymentInvoice.provider_payment_id == provider_payment_id,
        )
    ).first()


def list_invoices_by_account(
    db: Session, account_id: int, limit: int = 100
) -> list[PaymentInvoice]:
    """Счета аккаунта (свежие первыми)."""
    stmt = (
        select(PaymentInvoice)
        .where(PaymentInvoice.account_id == account_id)
        .order_by(PaymentInvoice.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def set_invoice_status(
    db: Session, invoice: PaymentInvoice, status: str, paid_at: datetime | None = None
) -> PaymentInvoice:
    """Обновить статус счёта (и дату оплаты)."""
    invoice.status = status
    if paid_at is not None:
        invoice.paid_at = paid_at
    db.commit()
    db.refresh(invoice)
    return invoice


# --- Transactions ---


def create_transaction(db: Session, **fields: Any) -> PaymentTransaction:
    """Создать транзакцию по счёту."""
    tx = PaymentTransaction(**fields)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


# --- Webhook logs ---


def create_webhook_log(db: Session, **fields: Any) -> PaymentWebhookLog:
    """Записать входящий вебхук (санитизированный)."""
    log = PaymentWebhookLog(**fields)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def get_processed_webhook_by_event_id(
    db: Session, provider: str, provider_event_id: str
) -> PaymentWebhookLog | None:
    """Вернуть УЖЕ ОБРАБОТАННЫЙ вебхук по (provider, provider_event_id) или None.

    Основа идемпотентности: если такое событие уже обработано (``status=processed``),
    повторный вебхук игнорируется и баланс не пополняется второй раз.
    """
    return db.scalars(
        select(PaymentWebhookLog).where(
            PaymentWebhookLog.provider == provider,
            PaymentWebhookLog.provider_event_id == provider_event_id,
            PaymentWebhookLog.status == "processed",
        )
    ).first()


def list_webhook_logs_by_provider(
    db: Session, provider: str, limit: int = 100
) -> list[PaymentWebhookLog]:
    """Журнал вебхуков провайдера (свежие первыми)."""
    stmt = (
        select(PaymentWebhookLog)
        .where(PaymentWebhookLog.provider == provider)
        .order_by(PaymentWebhookLog.id.desc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
