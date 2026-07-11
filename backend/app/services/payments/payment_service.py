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
    ACTION_INVOICE_CANCELED,
    ACTION_INVOICE_CREATED,
    ACTION_INVOICE_EXPIRED,
    ACTION_INVOICE_FAILED,
    ACTION_INVOICE_PAID,
    AuditLogService,
)
from app.services.billing_service import BillingService
from app.services.payments.cloudpayments_service import CloudPaymentsProvider
from app.services.payments.mock_payment_service import MockPaymentProvider
from app.services.payments.payment_provider import (
    STATUS_CANCELED,
    STATUS_DRAFT,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PAID,
    STATUS_PENDING,
    TX_STATUS_CANCELED,
    TX_STATUS_FAILED,
    TX_STATUS_SUCCEEDED,
    WEBHOOK_STATUS_FAILED,
    WEBHOOK_STATUS_IGNORED,
    WEBHOOK_STATUS_PROCESSED,
    PaymentProvider,
    PaymentProviderError,
    PaymentWebhookResult,
    WebhookSignatureError,
)
from app.services.payments.robokassa_payment_service import RobokassaPaymentProvider
from app.services.payments.tbank_payment_service import TBankPaymentProvider
from app.services.payments.yookassa_payment_service import YooKassaPaymentProvider

# Статус счёта → (статус транзакции, audit-action) для неуспешных терминальных исходов.
_UNPAID_TERMINAL: dict[str, tuple[str, str]] = {
    STATUS_FAILED: (TX_STATUS_FAILED, ACTION_INVOICE_FAILED),
    STATUS_CANCELED: (TX_STATUS_CANCELED, ACTION_INVOICE_CANCELED),
    STATUS_EXPIRED: (TX_STATUS_CANCELED, ACTION_INVOICE_EXPIRED),
}


def _build_registry(settings: Settings) -> dict[str, PaymentProvider]:
    return {
        MockPaymentProvider.name: MockPaymentProvider(),
        YooKassaPaymentProvider.name: YooKassaPaymentProvider(settings),
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
        self._registry = registry or _build_registry(self._settings)
        self._audit = audit_service or AuditLogService(self._settings)

    # --- Провайдеры ---------------------------------------------------- #

    def _provider_usable(self, name: str, provider: PaymentProvider) -> bool:
        """Можно ли создавать счёт у провайдера: mock, live-поддержка или sandbox."""
        if name == "mock":
            return True
        if self._settings.payments_live_enabled and provider.live_supported:
            return True
        return self._settings.payment_provider_sandbox_enabled(name)

    def available_providers(self) -> list[dict[str, Any]]:
        """Список провайдеров и их доступность (для UI)."""
        live = self._settings.payments_live_enabled
        out: list[dict[str, Any]] = []
        for name, provider in self._registry.items():
            sandbox = self._settings.payment_provider_sandbox_enabled(name)
            if name == "mock":
                mode = "mock"
            elif live and provider.live_supported:
                mode = "live"
            elif sandbox:
                mode = "sandbox"
            else:
                mode = "planned"
            out.append(
                {
                    "provider": name,
                    "live_supported": provider.live_supported,
                    "sandbox_enabled": sandbox,
                    "usable": self._provider_usable(name, provider),
                    "mode": mode,
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
        # Провайдер доступен, только если это mock, включён live с live-поддержкой,
        # либо у провайдера включён sandbox-режим. Иначе — понятная ошибка.
        provider_impl_check = self._get_provider(provider_name)
        if not self._provider_usable(provider_name, provider_impl_check):
            raise PaymentProviderError(
                f"Провайдер {provider_name} недоступен: боевые платежи выключены "
                f"(PAYMENTS_LIVE_ENABLED=false) и sandbox не включён. Используйте mock."
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

    def set_invoice_amount(self, db: Session, invoice_id: int, amount_units: int) -> Any:
        """Изменить сумму счёта — ТОЛЬКО пока он в статусе draft (immutable после pending).

        Гарантия: после перехода в pending/оплату сумму счёта изменить нельзя
        (защита от подмены суммы уже выставленного/оплаченного счёта).
        """
        invoice = payment_repository.get_invoice(db, invoice_id)
        if invoice is None:
            raise PaymentProviderError(f"Счёт #{invoice_id} не найден")
        if invoice.status != STATUS_DRAFT:
            raise PaymentProviderError(
                f"Сумму счёта #{invoice_id} нельзя менять в статусе {invoice.status}: "
                "она фиксируется после выставления (pending)."
            )
        if amount_units <= 0:
            raise PaymentProviderError("Сумма пополнения должна быть положительной")
        invoice.amount_units = amount_units
        invoice.amount_rub = self.units_to_rub(amount_units)
        db.commit()
        db.refresh(invoice)
        return invoice

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
            status=TX_STATUS_SUCCEEDED,
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

    def _mark_unpaid_terminal(self, db: Session, invoice_id: int, target_status: str) -> Any:
        """Перевести счёт в неуспешный терминальный статус (failed/canceled/expired).

        Баланс НЕ пополняется. Идемпотентно: если счёт уже в целевом статусе — просто
        вернуть его. Оплаченный счёт менять нельзя (баланс уже пополнен).
        """
        invoice = payment_repository.get_invoice(db, invoice_id)
        if invoice is None:
            raise PaymentProviderError(f"Счёт #{invoice_id} не найден")
        if invoice.status == target_status:
            return invoice  # идемпотентно
        if invoice.status == STATUS_PAID:
            raise PaymentProviderError(
                f"Счёт #{invoice_id} уже оплачен — перевести в {target_status} нельзя."
            )
        tx_status, action = _UNPAID_TERMINAL[target_status]
        payment_repository.set_invoice_status(db, invoice, target_status)
        payment_repository.create_transaction(
            db,
            invoice_id=invoice.id,
            account_id=invoice.account_id,
            provider=invoice.provider,
            provider_payment_id=invoice.provider_payment_id,
            status=tx_status,
            amount_units=0,
            amount_rub=0,
            raw_payload_sanitized={"source": f"mock-{target_status}", "credited": False},
        )
        self._audit.record(
            db,
            action,
            account_id=invoice.account_id,
            entity_type="invoice",
            entity_id=invoice.id,
            metadata={"provider": invoice.provider, "status": target_status, "credited": False},
        )
        return invoice

    def mock_fail(self, db: Session, invoice_id: int) -> Any:
        """Отметить счёт неуспешным (failed). Баланс не пополняется. Идемпотентно."""
        return self._mark_unpaid_terminal(db, invoice_id, STATUS_FAILED)

    def mock_cancel(self, db: Session, invoice_id: int) -> Any:
        """Отменить счёт (canceled). Баланс не пополняется. Идемпотентно."""
        return self._mark_unpaid_terminal(db, invoice_id, STATUS_CANCELED)

    def mock_expire(self, db: Session, invoice_id: int) -> Any:
        """Просрочить счёт (expired). Баланс не пополняется. Идемпотентно."""
        return self._mark_unpaid_terminal(db, invoice_id, STATUS_EXPIRED)

    # --- Вебхуки ------------------------------------------------------- #

    def _record_webhook(
        self,
        db: Session,
        provider_name: str,
        result: PaymentWebhookResult,
        status: str,
        *,
        error_message: str | None = None,
    ) -> None:
        """Записать журнал вебхука (санитизированный, со статусом обработки)."""
        safe_payload = sanitize_metadata(result.payload_sanitized)
        payment_repository.create_webhook_log(
            db,
            provider=provider_name,
            event_type=result.event_type,
            provider_payment_id=result.provider_payment_id,
            provider_event_id=result.provider_event_id,
            payload_sanitized=safe_payload if isinstance(safe_payload, dict) else {},
            signature_valid=result.signature_valid,
            processed=status == WEBHOOK_STATUS_PROCESSED,
            status=status,
            processed_at=datetime.now(UTC) if status == WEBHOOK_STATUS_PROCESSED else None,
            error_message=error_message,
        )

    def handle_webhook(
        self,
        db: Session,
        provider: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Обработать вебхук провайдера: залогировать, проверить подпись, пополнить.

        - Неизвестный провайдер → ошибка (API → 400).
        - Недоверенная подпись: в production — отказ (``WebhookSignatureError`` → 403),
          в local/mock — вебхук просто не обрабатывается (лог status=failed).
        - Дубликат по ``provider_event_id`` (уже обработан) → игнор, без пополнения.
        - Дубликат по уже оплаченному счёту → идемпотентно, без двойного пополнения.
        - Payload сохраняется санитизированным (без секретов/подписей).
        """
        provider_name = (provider or "").strip().lower()
        provider_impl = self._get_provider(provider_name)  # бросит на неизвестном
        result = provider_impl.handle_webhook(payload, headers)

        # 1) Подпись. В production недоверенный вебхук отклоняется (403).
        if not result.signature_valid:
            self._record_webhook(
                db, provider_name, result, WEBHOOK_STATUS_FAILED, error_message="signature_invalid"
            )
            if self._settings.is_production or self._settings.payments_live_enabled:
                raise WebhookSignatureError("Подпись вебхука не подтверждена — запрос отклонён.")
            return self._webhook_response(
                provider_name, False, False, None, "Подпись не подтверждена — вебхук не обработан."
            )

        # 2) Идемпотентность по provider_event_id (событие уже обработано ранее).
        if result.provider_event_id:
            prior = payment_repository.get_processed_webhook_by_event_id(
                db, provider_name, result.provider_event_id
            )
            if prior is not None:
                self._record_webhook(db, provider_name, result, WEBHOOK_STATUS_IGNORED)
                return self._webhook_response(
                    provider_name,
                    False,
                    True,
                    None,
                    "Дубликат события (provider_event_id) — пополнения нет.",
                )

        # 3) Ищем счёт по provider_payment_id.
        invoice = None
        if result.provider_payment_id:
            invoice = payment_repository.get_invoice_by_provider_payment_id(
                db, provider_name, result.provider_payment_id
            )
        if invoice is None:
            self._record_webhook(
                db, provider_name, result, WEBHOOK_STATUS_IGNORED, error_message="invoice_not_found"
            )
            return self._webhook_response(
                provider_name, False, False, None, "Счёт по вебхуку не найден."
            )

        # 4) Успешная оплата (один раз).
        if result.status == STATUS_PAID and invoice.status != STATUS_PAID:
            self._mark_paid_and_credit(db, invoice, source=f"{provider_name}-webhook")
            self._record_webhook(db, provider_name, result, WEBHOOK_STATUS_PROCESSED)
            return self._webhook_response(
                provider_name, True, False, invoice.id, "Счёт оплачен, баланс пополнен."
            )

        # 5) Дубликат по уже оплаченному счёту / непроцессируемый статус.
        self._record_webhook(db, provider_name, result, WEBHOOK_STATUS_IGNORED)
        return self._webhook_response(
            provider_name,
            False,
            invoice.status == STATUS_PAID,
            invoice.id,
            "Дубликат/непроцессируемый статус — пополнения нет.",
        )

    @staticmethod
    def _webhook_response(
        provider_name: str,
        processed: bool,
        duplicate: bool,
        invoice_id: int | None,
        message: str,
    ) -> dict[str, Any]:
        """Собрать унифицированный ответ обработки вебхука."""
        return {
            "provider": provider_name,
            "accepted": True,
            "processed": processed,
            "duplicate": duplicate,
            "invoice_id": invoice_id,
            "message": message,
        }


def get_payment_service() -> PaymentService:
    """DI-фабрика сервиса платежей (mock по умолчанию, live выключен)."""
    return PaymentService()
