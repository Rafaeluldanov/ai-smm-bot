"""Тесты UI платежей /ui/billing (offline, TestClient).

Методы (карта/СБП/QR/счёт), провайдеры (mock/sandbox), баннер выключенных боевых
платежей, отсутствие секретов провайдеров в HTML.
"""

from fastapi.testclient import TestClient

from app.config import get_settings

BILLING = "/ui/billing"


def test_billing_has_payment_methods(client: TestClient) -> None:
    body = client.get(BILLING).text
    for method in ("Банковская карта", "СБП", "QR-код", "Счёт для ИП", "Счёт для ООО"):
        assert method in body, method


def test_billing_has_amount_presets_and_create(client: TestClient) -> None:
    body = client.get(BILLING).text
    for amount in ("100", "500", "1000", "5000", "10000"):
        assert f"setAmt({amount})" in body, amount
    assert "Создать счёт" in body
    assert "createInvoice(" in body


def test_billing_has_provider_and_profile(client: TestClient) -> None:
    body = client.get(BILLING).text
    assert "/billing/providers" in body  # провайдеры подгружаются
    assert "Реквизиты плательщика" in body
    for field in ("customer_type", "inn", "kpp", "ogrn", "email", "phone"):
        assert field in body, field


def test_billing_live_disabled_banner(client: TestClient) -> None:
    # По умолчанию боевые платежи выключены — показан баннер.
    body = client.get(BILLING).text
    assert "Боевые платежи выключены" in body
    assert "mock/sandbox" in body


def test_billing_no_provider_secrets_in_html(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.yookassa_secret_key,
        settings.yookassa_webhook_secret,
        settings.tbank_password,
        settings.cloudpayments_api_secret,
        settings.robokassa_password1,
        settings.robokassa_password2,
    ]
    body = client.get(BILLING).text
    for secret in secrets:
        if secret:
            assert secret not in body


def test_billing_page_opens(client: TestClient) -> None:
    assert client.get(BILLING).status_code == 200
