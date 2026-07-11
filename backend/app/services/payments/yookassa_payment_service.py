"""YooKassa (ЮKassa): sandbox-adapter провайдера. Реальная сеть НЕ вызывается.

Безопасность:
- Боевой HTTP-эквайринг в этом релизе НЕ реализован. Реальные вызовы к API стоят за
  флагом ``PAYMENTS_PROVIDER_HTTP_ENABLED`` (по умолчанию false) — при включённом флаге
  провайдер честно бросает ошибку, а не делает вид, что платёж прошёл.
- Sandbox (``YOOKASSA_SANDBOX_ENABLED=true``) создаёт ДЕТЕРМИНИРОВАННЫЙ fake-счёт без
  сети — удобно для e2e-прогонов оплаты.
- Секреты (shop_id / secret_key / webhook_secret) читаются из конфига и НИКОГДА не
  логируются, не кладутся в payload и не возвращаются наружу.
- Вебхук считается доверенным только при валидной подписи; без webhook-секрета в
  production вебхук отклоняется (см. PaymentService.handle_webhook → HTTP 403).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from app.config import Settings, get_settings
from app.core.redaction import sanitize_metadata
from app.services.payments.payment_provider import (
    QR_METHODS,
    STATUS_CANCELED,
    STATUS_PAID,
    STATUS_PENDING,
    PaymentInvoiceResult,
    PaymentProviderError,
    PaymentStatusResult,
    PaymentWebhookResult,
)

# Сопоставление метода Botfleet → payment_method_data.type YooKassa.
_METHOD_TYPE: dict[str, str] = {
    "bank_card": "bank_card",
    "sbp": "sbp",
    "qr": "sbp",  # QR реализуется через СБП
}
# Сопоставление статуса объекта платежа YooKassa → статус счёта Botfleet.
_YK_STATUS: dict[str, str] = {
    "succeeded": STATUS_PAID,
    "waiting_for_capture": STATUS_PENDING,
    "pending": STATUS_PENDING,
    "canceled": STATUS_CANCELED,
}


def _canonical(payload: dict[str, Any]) -> str:
    """Каноническая сериализация тела для подписи (стабильный порядок ключей)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_yookassa_payment_payload(
    invoice: Any,
    method: str,
    customer: dict[str, Any] | None = None,
    *,
    return_url: str = "",
    confirmation_type: str = "redirect",
) -> dict[str, Any]:
    """Собрать САНИТИЗИРОВАННЫЙ payload запроса создания платежа YooKassa.

    Секреты сюда не попадают (только сумма/метаданные/метод). Значение суммы — строка
    с двумя знаками (требование YooKassa), валюта RUB. Реальный HTTP не выполняется.
    """
    amount_rub = int(getattr(invoice, "amount_rub", 0) or 0)
    payload: dict[str, Any] = {
        "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
        "capture": True,
        "confirmation": {
            "type": (confirmation_type or "redirect").strip() or "redirect",
            "return_url": (return_url or "/ui/billing").strip(),
        },
        "description": f"Пополнение баланса Botfleet ({getattr(invoice, 'amount_units', 0)} units)",
        "metadata": {
            "account_id": getattr(invoice, "account_id", None),
            "invoice_id": getattr(invoice, "id", None),
            "amount_units": getattr(invoice, "amount_units", None),
        },
    }
    method_type = _METHOD_TYPE.get((method or "").strip().lower())
    if method_type:
        payload["payment_method_data"] = {"type": method_type}
    if customer and customer.get("email"):
        # Чек по 54-ФЗ формирует провайдер; передаём только email (не секрет).
        payload["receipt"] = {"customer": {"email": customer["email"]}}
    # Defense-in-depth: прогоняем через sanitize (на случай секретов в customer/return_url).
    cleaned = sanitize_metadata(payload)
    return cleaned if isinstance(cleaned, dict) else {}


def verify_yookassa_signature(
    payload: dict[str, Any], headers: dict[str, str] | None, secret: str
) -> bool:
    """Проверить подпись вебхука (placeholder: HMAC-SHA256 по каноническому телу).

    Без секрета или заголовка подписи — не доверяем (False). Настоящая YooKassa
    использует IP-allowlist/уведомления; здесь — детерминированная HMAC-проверка для
    sandbox-тестов и как каркас для live-подключения.
    """
    if not secret:
        return False
    low = {str(k).lower(): v for k, v in (headers or {}).items()}
    provided = low.get("x-yookassa-signature") or low.get("x-signature")
    if not provided:
        return False
    expected = hmac.new(secret.encode("utf-8"), _canonical(payload).encode("utf-8"), hashlib.sha256)
    return hmac.compare_digest(str(provided), expected.hexdigest())


class YooKassaPaymentProvider:
    """Sandbox-adapter YooKassa (bank_card/sbp/qr). Боевой HTTP не реализован."""

    name = "yookassa"
    live_supported = False

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def _fake_id(self, account_id: int, idempotency_key: str | None) -> str:
        seed = f"yookassa:{account_id}:{idempotency_key or ''}"
        return "yoo_sandbox_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]

    def create_invoice(
        self,
        account_id: int,
        amount_units: int,
        amount_rub: int,
        method: str,
        customer: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> PaymentInvoiceResult:
        if self._settings.payments_provider_http_enabled:
            # Явно НЕ делаем реальный сетевой вызов в этом релизе.
            raise PaymentProviderError(
                "Реальные HTTP-вызовы к YooKassa ещё не реализованы "
                "(PAYMENTS_PROVIDER_HTTP_ENABLED=true). Отключите флаг или используйте sandbox."
            )
        if not self._settings.yookassa_sandbox_enabled:
            raise PaymentProviderError(
                "YooKassa доступен только в sandbox (YOOKASSA_SANDBOX_ENABLED=true). "
                "Боевой эквайринг выключен — используйте mock-провайдер."
            )
        pid = self._fake_id(account_id, idempotency_key)
        payload = build_yookassa_payment_payload(
            _InvoiceLike(account_id, amount_units, amount_rub),
            method,
            customer,
            return_url=self._settings.yookassa_return_url_effective,
            confirmation_type=self._settings.yookassa_confirmation_type,
        )
        qr = None
        if (method or "").strip().lower() in QR_METHODS:
            qr = f"https://yookassa.sandbox/qr/{pid}?amount={amount_rub}"
        return PaymentInvoiceResult(
            provider=self.name,
            provider_payment_id=pid,
            status=STATUS_PENDING,
            payment_url=f"https://yookassa.sandbox/confirm/{pid}",
            qr_payload=qr,
            amount_rub=amount_rub,
            sandbox=True,
            metadata={
                "method": method,
                "sandbox": True,
                "confirmation_type": self._settings.yookassa_confirmation_type,
                "payment_method_type": payload.get("payment_method_data", {}).get("type"),
            },
        )

    def get_payment_status(self, provider_payment_id: str) -> PaymentStatusResult:
        # Sandbox не хранит состояние — статус ведёт БД счёта; возвращаем pending.
        return PaymentStatusResult(
            provider=self.name, provider_payment_id=provider_payment_id, status=STATUS_PENDING
        )

    def handle_webhook(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> PaymentWebhookResult:
        """Разобрать вебхук YooKassa. Доверяем только при валидной подписи."""
        secret = (self._settings.yookassa_webhook_secret or "").strip()
        valid = verify_yookassa_signature(payload, headers, secret)
        obj_raw = payload.get("object")
        obj: dict[str, Any] = obj_raw if isinstance(obj_raw, dict) else {}
        event = str(payload.get("event", ""))
        pid = obj.get("id") or payload.get("provider_payment_id")
        yk_status = str(obj.get("status", payload.get("status", "")))
        status = _YK_STATUS.get(yk_status, "")
        event_id = payload.get("event_id") or (f"{event}:{pid}" if pid else None)
        return PaymentWebhookResult(
            provider=self.name,
            event_type=event,
            provider_payment_id=str(pid) if pid else None,
            status=status,
            signature_valid=valid,
            payload_sanitized={"event": event, "status": yk_status},
            provider_event_id=str(event_id) if event_id else None,
        )


class _InvoiceLike:
    """Лёгкий носитель полей счёта для построения payload (без БД-объекта)."""

    def __init__(self, account_id: int, amount_units: int, amount_rub: int) -> None:
        self.id: int | None = None
        self.account_id = account_id
        self.amount_units = amount_units
        self.amount_rub = amount_rub
