"""YooKassa: sandbox-скелет провайдера. Сеть не вызывается на этом этапе.

Реальные платежи выключены (``PAYMENTS_LIVE_ENABLED=false``): создание счёта бросает
``PaymentProviderError``. Секреты (shop_id/secret_key/webhook_secret) читаются из
конфига и НЕ логируются/не возвращаются.
"""

from __future__ import annotations

from typing import Any

from app.services.payments.payment_provider import (
    PaymentProviderError,
    PaymentStatusResult,
    PaymentWebhookResult,
)


class YooKassaPaymentProvider:
    """Sandbox-скелет YooKassa (bank_card/sbp/qr). Live пока не реализован."""

    name = "yookassa"
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
            "YooKassa sandbox ещё не подключён: реальные платежи выключены "
            "(PAYMENTS_LIVE_ENABLED=false). Используйте mock-провайдер."
        )

    def get_payment_status(self, provider_payment_id: str) -> PaymentStatusResult:
        raise PaymentProviderError("YooKassa: статус недоступен (sandbox-скелет).")

    def handle_webhook(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> PaymentWebhookResult:
        # Без секрета подпись не проверяем — вебхук не доверенный (не обрабатывается).
        return PaymentWebhookResult(
            provider=self.name,
            event_type=str(payload.get("event", "")),
            provider_payment_id=None,
            status="",
            signature_valid=False,
            payload_sanitized={"event": str(payload.get("event", ""))},
        )
