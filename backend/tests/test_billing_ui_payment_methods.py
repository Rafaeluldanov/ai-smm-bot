"""Тесты UI /ui/billing: методы оплаты, провайдеры, баннеры, безопасность (нет карты)."""

from fastapi.testclient import TestClient

from app.config import get_settings

BILLING = "/ui/billing"


def test_all_payment_methods_present(client: TestClient) -> None:
    body = client.get(BILLING).text
    for method in ("Банковская карта", "СБП", "QR", "Счёт для ИП", "Счёт для ООО"):
        assert method in body, method


def test_provider_selector_and_modes(client: TestClient) -> None:
    body = client.get(BILLING).text
    # Провайдеры подгружаются с режимом (mock/sandbox); дефолтный провайдер виден.
    assert "/billing/providers" in body
    assert "mock/sandbox" in body
    assert "Провайдер" in body


def test_payments_live_disabled_banner(client: TestClient) -> None:
    body = client.get(BILLING).text
    assert "Боевые платежи выключены" in body
    assert "PAYMENTS_LIVE_ENABLED=false" in body


def test_no_card_collection_fields(client: TestClient) -> None:
    body = client.get(BILLING).text.lower()
    # Botfleet НЕ собирает данные карты — не должно быть ПОЛЕЙ ВВОДА номера/cvv/срока.
    for banned in (
        "card_number",
        "id='card",
        "name='card",
        "id='pan'",
        "id='cvv'",
        "id='cvc'",
        'autocomplete="cc-number"',
        "cc-number",
    ):
        assert banned not in body, banned
    # Есть явное предупреждение про ввод карты только у провайдера.
    assert "не вводите банковскую карту" in body


def test_readiness_and_warnings(client: TestClient) -> None:
    body = client.get(BILLING).text
    assert "profile-readiness" in body
    assert "Mock-pay доступен только в local/sandbox" in body


def test_no_provider_secrets_in_html(client: TestClient) -> None:
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
