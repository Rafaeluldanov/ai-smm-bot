"""Оркестрация платежей: счета, mock-оплата, вебхуки, пополнение баланса.

Правила безопасности:
- создание счёта НЕ меняет баланс;
- баланс пополняется ТОЛЬКО после статуса ``paid`` (mock-pay/webhook), один раз
  (идемпотентно по ключу счёта);
- реальные провайдеры недоступны без ``PAYMENTS_LIVE_ENABLED=true`` — счёт создаёт
  только mock (или падает понятной ошибкой);
- неуспешный/отменённый счёт не пополняет;
- дублирующийся вебхук идемпотентен;
- секреты провайдеров не попадают в БД/ответы (payload санитизируется).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.redaction import sanitize_metadata
from app.repositories import payment_repository
from app.services.audit_log_service import (
    ACTION_INVOICE_CREATED,
    ACTION_INVOICE_PAID,
    AuditLogService,
)
from app.services.billing_service import BillingService
from app.services.payments.cloudpayments_service import CloudPaymentsProvider
from app.services.payments.mock_payment_service import MockPaymentProvider
from app.services.payments.payment_provider import (
    STATUS_CANCELED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PAID,
    STATUS_PENDING,
    PaymentProvider,
    PaymentProviderError,
)
from app.services.payments.robokassa_payment_service import RobokassaPaymentProvider
from app.services.payments.tbank_payment_service import TBankPaymentProvider
from app.services.payments.yookassa_payment_service import YooKassaPaymentProvider


def _build_registry() -> dict[str, PaymentProvider]:
    return {
        MockPaymentProvider.name: MockPaymentProvider(),
        YooKassaPaymentProvider.name: YooKassaPaymentProvider(),
        TBankPaymentProvider.name: TBankPaymentProvider(),
        CloudPaymentsProvider.name: CloudPaymentsProvider(),
        RobokassaPaymentProvider.name: RobokassaPaymentProvider(),
    }


class PaymentService:
    """Счета/оплата/вебхуки поверх ``BillingService`` (пополнение баланса)."""

    def __init__(
        self,
        billing_service: BillingService | None = None,
        settings: Settings | None = None,
        registry: dict[str, PaymentProvider] | None = None,
        audit_service: AuditLogService | None = None,
    ) -> None:
        self._billing = billing_service or BillingService()
        self._settings = settings or get_settings()
        self._registry = registry or _build_registry()
        self._audit = audit_service or AuditLogService(self._settings)

    # --- Провайдеры ---------------------------------------------------- #

    def available_providers(self) -> list[dict[str, Any]]:
        """Список провайдеров и их доступность (для UI)."""
        live = self._settings.payments_live_enabled
        out: list[dict[str, Any]] = []
        for name, provider in self._registry.items():
            usable = name == "mock" or (live and provider.live_supported)
            out.append(
                {
                    "provider": name,
                    "live_supported": provider.live_supported,
                    "usable": usable,
                    "mode": "mock" if name == "mock" else ("live" if live else "sandbox"),
                }
            )
        return out

    def _get_provider(self, name: str) -> PaymentProvider:
        provider = self._registry.get(name)
        if provider is None:
            raise PaymentProviderError(f"Неизвестный провайдер: {name!r}")
        return provider

    def _resolve_provider_name(self, provider: str | None) -> str:
        return (provider or self._settings.payments_default_provider or "mock").strip().lower()

    def units_to_rub(self, amount_units: int) -> int:
        """Пересчитать units → рубли по ориентировочной цене (округление вверх)."""
        return int(math.ceil(max(0, amount_units) * self._settings.billing_unit_price_rub))

    def topup_preview(
        self,
        account_id: int,
        amount_units: int,
        method: str = "bank_card",
        provider: str | None = None,
    ) -> dict[str, Any]:
        """Оценка пополнения (units → рубли), без создания счёта. Бесплатно."""
        provider_name = self._resolve_provider_name(provider)
        return {
            "amount_units": amount_units,
            "amount_rub": self.units_to_rub(amount_units),
            "method": method,
            "provider": provider_name,
            "payments_live_enabled": self._settings.payments_live_enabled,
            "note": (
                "Боевые платежи выключены — будет создан mock/sandbox счёт."
                if not self._settings.payments_live_enabled
                else "Боевые платежи включены."
            ),
        }

    # --- Счета --------------------------------------------------------- #

    def create_invoice(
        self,
        db: Session,
        account_id: int,
        amount_units: int,
        method: str = "bank_card",
        provider: str | None = None,
        customer: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """Создать счёт (не меняет баланс). Идемпотентно по ключу."""
        if amount_units <= 0:
            raise PaymentProviderError("Сумма пополнения должна быть положительной")
        provider_name = self._resolve_provider_name(provider)
        # Реальные провайдеры недоступны без live-флага (кроме mock).
        if provider_name != "mock" and not self._settings.payments_live_enabled:
            raise PaymentProviderError(
                f"Провайдер {provider_name} недоступен: боевые платежи выключены "
                "(PAYMENTS_LIVE_ENABLED=false). Используйте mock."
            )
        if idempotency_key:
            existing = payment_repository.get_invoice_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing

        provider_impl = self._get_provider(provider_name)
        amount_rub = self.units_to_rub(amount_units)
        if customer:
            payment_repository.upsert_profile(db, account_id, customer)

        result = provider_impl.create_invoice(
            account_id=account_id,
            amount_units=amount_units,
            amount_rub=amount_rub,
            method=method,
            customer=customer,
            idempotency_key=idempotency_key,
        )
        invoice = payment_repository.create_invoice(
            db,
            account_id=account_id,
            provider=provider_name,
            method=method,
            amount_units=amount_units,
            amount_rub=amount_rub,
            status=result.status or STATUS_PENDING,
            payment_url=result.payment_url,
            qr_payload=result.qr_payload,
            provider_payment_id=result.provider_payment_id,
            idempotency_key=idempotency_key,
            invoice_metadata={"sandbox": result.sandbox, **(result.metadata or {})},
        )
        self._audit.record(
            db,
            ACTION_INVOICE_CREATED,
            account_id=account_id,
            entity_type="invoice",
            entity_id=invoice.id,
            metadata={"provider": provider_name, "method": method, "amount_units": amount_units},
        )
        return invoice

    def list_invoices(self, db: Session, account_id: int, limit: int = 100) -> list[Any]:
        """Счета аккаунта (свежие первыми)."""
        return payment_repository.list_invoices_by_account(db, account_id, limit)

    def get_invoice(self, db: Session, invoice_id: int) -> Any:
        """Вернуть счёт по id (или None)."""
        return payment_repository.get_invoice(db, invoice_id)

    # --- Оплата и пополнение баланса ----------------------------------- #

    def _credit_once(self, db: Session, invoice: Any, source: str) -> None:
        """Пополнить баланс за оплаченный счёт ровно один раз (идемпотентно)."""
        self._billing.manual_topup(
            db,
            invoice.account_id,
            invoice.amount_units,
            idempotency_key=f"invoice-{invoice.id}-paid",
            description=f"Пополнение по счёту #{invoice.id} ({source})",
        )

    def _mark_paid_and_credit(self, db: Session, invoice: Any, source: str) -> Any:
        """Отметить счёт оплаченным, записать транзакцию и пополнить баланс."""
        now = datetime.now(UTC)
        payment_repository.set_invoice_status(db, invoice, STATUS_PAID, paid_at=now)
        payment_repository.create_transaction(
            db,
            invoice_id=invoice.id,
            account_id=invoice.account_id,
            provider=invoice.provider,
            provider_payment_id=invoice.provider_payment_id,
            status=STATUS_PAID,
            amount_units=invoice.amount_units,
            amount_rub=invoice.amount_rub,
            raw_payload_sanitized={"source": source, "mock": invoice.provider == "mock"},
        )
        self._credit_once(db, invoice, source)
        self._audit.record(
            db,
            ACTION_INVOICE_PAID,
            account_id=invoice.account_id,
            entity_type="invoice",
            entity_id=invoice.id,
            metadata={
                "provider": invoice.provider,
                "amount_units": invoice.amount_units,
                "source": source,
            },
        )
        return invoice

    def mock_pay(self, db: Session, invoice_id: int) -> Any:
        """Подтвердить mock-оплату счёта: paid + пополнение баланса (один раз).

        Идемпотентно: повторный вызов не пополняет баланс дважды. Только для
        mock-провайдера (или когда боевые платежи выключены).
        """
        invoice = payment_repository.get_invoice(db, invoice_id)
        if invoice is None:
            raise PaymentProviderError(f"Счёт #{invoice_id} не найден")
        if invoice.provider != "mock" and self._settings.payments_live_enabled:
            raise PaymentProviderError("mock-pay доступен только для mock-провайдера.")
        if invoice.status == STATUS_PAID:
            return invoice  # уже оплачен — второй раз не пополняем
        if invoice.status in (STATUS_CANCELED, STATUS_FAILED, STATUS_EXPIRED):
            raise PaymentProviderError(
                f"Счёт #{invoice_id} в статусе {invoice.status}: оплатить нельзя."
            )
        return self._mark_paid_and_credit(db, invoice, source="mock-pay")

    # --- Вебхуки ------------------------------------------------------- #

    def handle_webhook(
        self,
        db: Session,
        provider: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Обработать вебхук провайдера: залогировать, проверить, пополнить.

        Неизвестный провайдер → ошибка. Недоверенная подпись → не обрабатывается.
        Дублирующийся вебхук по уже оплаченному счёту — идемпотентен (без двойного
        пополнения). Payload сохраняется санитизированным (без секретов).
        """
        provider_name = (provider or "").strip().lower()
        provider_impl = self._get_provider(provider_name)  # бросит на неизвестном
        result = provider_impl.handle_webhook(payload, headers)
        # Defense-in-depth: чистим payload от секретов/подписей перед записью в БД.
        safe_payload = sanitize_metadata(result.payload_sanitized)
        payment_repository.create_webhook_log(
            db,
            provider=provider_name,
            event_type=result.event_type,
            provider_payment_id=result.provider_payment_id,
            payload_sanitized=safe_payload,
            signature_valid=result.signature_valid,
            processed=False,
        )
        if not result.signature_valid:
            return {
                "provider": provider_name,
                "accepted": True,
                "processed": False,
                "duplicate": False,
                "invoice_id": None,
                "message": "Подпись не подтверждена — вебхук не обрабатывается.",
            }
        invoice = None
        if result.provider_payment_id:
            invoice = payment_repository.get_invoice_by_provider_payment_id(
                db, provider_name, result.provider_payment_id
            )
        if invoice is None:
            return {
                "provider": provider_name,
                "accepted": True,
                "processed": False,
                "duplicate": False,
                "invoice_id": None,
                "message": "Счёт по вебхуку не найден.",
            }
        if result.status == STATUS_PAID and invoice.status != STATUS_PAID:
            self._mark_paid_and_credit(db, invoice, source=f"{provider_name}-webhook")
            return {
                "provider": provider_name,
                "accepted": True,
                "processed": True,
                "duplicate": False,
                "invoice_id": invoice.id,
                "message": "Счёт оплачен, баланс пополнен.",
            }
        # Уже оплачен ранее — дубликат, без повторного пополнения.
        return {
            "provider": provider_name,
            "accepted": True,
            "processed": False,
            "duplicate": invoice.status == STATUS_PAID,
            "invoice_id": invoice.id,
            "message": "Дубликат/непроцессируемый статус — пополнения нет.",
        }


def get_payment_service() -> PaymentService:
    """DI-фабрика сервиса платежей (mock по умолчанию, live выключен)."""
    return PaymentService()
