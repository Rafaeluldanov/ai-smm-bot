"""Mock-провайдер платежей: fake invoice/payment_url без сети и реальных денег.

Всегда доступен в dev. Создаёт детерминированный ``provider_payment_id`` и ссылку на
внутреннюю mock-оплату. Оплата подтверждается через ``/billing/invoices/{id}/mock-pay``
или mock-вебхук. Секретов не использует.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.services.payments.payment_provider import (
    STATUS_PAID,
    STATUS_PENDING,
    PaymentInvoiceResult,
    PaymentStatusResult,
    PaymentWebhookResult,
)


class MockPaymentProvider:
    """Заглушка провайдера: имитирует счёт/ссылку/QR без внешних вызовов."""

    name = "mock"
    live_supported = True  # mock «доступен» всегда, но это не реальные деньги

    def _fake_id(self, account_id: int, idempotency_key: str | None) -> str:
        seed = f"{account_id}:{idempotency_key or ''}"
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return f"mock_{digest}"

    def create_invoice(
        self,
        account_id: int,
        amount_units: int,
        amount_rub: int,
        method: str,
        customer: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentInvoiceResult:
        pid = self._fake_id(account_id, idempotency_key)
        qr = None
        if method in ("sbp", "qr"):
            qr = f"mock-qr://sbp/{pid}?amount={amount_rub}"
        return PaymentInvoiceResult(
            provider=self.name,
            provider_payment_id=pid,
            status=STATUS_PENDING,
            payment_url=f"/ui/billing/mock-pay/{pid}",
            qr_payload=qr,
            amount_rub=amount_rub,
            sandbox=True,
            metadata={"method": method, "mock": True},
        )

    def get_payment_status(self, provider_payment_id: str) -> PaymentStatusResult:
        # Mock не хранит состояние — статус ведёт БД счёта; возвращаем pending.
        return PaymentStatusResult(
            provider=self.name, provider_payment_id=provider_payment_id, status=STATUS_PENDING
        )

    def handle_webhook(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> PaymentWebhookResult:
        """Разобрать mock-вебхук. Подпись всегда валидна (это dev-заглушка)."""
        event_type = str(payload.get("event", "payment.succeeded"))
        pid = payload.get("provider_payment_id") or payload.get("object_id")
        status = str(payload.get("status", STATUS_PAID))
        return PaymentWebhookResult(
            provider=self.name,
            event_type=event_type,
            provider_payment_id=str(pid) if pid else None,
            status=status,
            signature_valid=True,
            payload_sanitized={"event": event_type, "status": status},
        )
