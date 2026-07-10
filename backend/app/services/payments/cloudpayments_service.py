"""CloudPayments: sandbox-скелет провайдера. Сеть не вызывается.

Реальные платежи выключены. Секреты (public_id/api_secret) из конфига НЕ логируются.
"""

from __future__ import annotations

from typing import Any

from app.services.payments.payment_provider import (
    PaymentProviderError,
    PaymentStatusResult,
    PaymentWebhookResult,
)


class CloudPaymentsProvider:
    """Sandbox-скелет CloudPayments (bank_card/sbp). Live пока не реализован."""

    name = "cloudpayments"
    live_supported = False

    def create_invoice(
        self,
        account_id: int,
        amount_units: int,
        amount_rub: int,
        method: str,
        customer: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        raise PaymentProviderError(
            "CloudPayments sandbox ещё не подключён: реальные платежи выключены "
            "(PAYMENTS_LIVE_ENABLED=false). Используйте mock-провайдер."
        )

    def get_payment_status(self, provider_payment_id: str) -> PaymentStatusResult:
        raise PaymentProviderError("CloudPayments: статус недоступен (sandbox-скелет).")

    def handle_webhook(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> PaymentWebhookResult:
        return PaymentWebhookResult(
            provider=self.name,
            event_type=str(payload.get("event", "")),
            provider_payment_id=None,
            status="",
            signature_valid=False,
            payload_sanitized={"event": str(payload.get("event", ""))},
        )
