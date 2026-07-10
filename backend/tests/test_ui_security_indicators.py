"""Тесты UI-индикаторов безопасности (v0.3.1): метки, отсутствие секретов/publish-due."""

from fastapi.testclient import TestClient

from app.config import get_settings


def test_settings_page_security_labels(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    for label in (
        "Live-публикации выключены по умолчанию",
        "Секреты показываются только маской",
        "Платные действия требуют баланс",
        "Preview / dry-run бесплатны",
    ):
        assert label in body, label


def test_billing_page_payments_disabled_indicator(client: TestClient) -> None:
    body = client.get("/ui/billing").text
    assert "PAYMENTS_LIVE_ENABLED=false" in body
    assert "Боевые платежи выключены" in body
    assert "mock/sandbox" in body


def test_analytics_page_estimated_units(client: TestClient) -> None:
    body = client.get("/ui/analytics").text
    assert "an-estimate" in body
    assert "estimated" in body.lower()
    # Кнопка становится «Пополнить баланс» при нехватке (disabled/warning).
    assert "Пополнить баланс" in body


def test_ui_pages_have_no_publish_due(client: TestClient) -> None:
    for path in ("/ui/settings", "/ui/billing", "/ui/analytics", "/ui/projects/1/dashboard"):
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


def test_ui_pages_no_live_enabled_true(client: TestClient) -> None:
    for path in ("/ui/settings", "/ui/billing", "/ui/analytics"):
        body = client.get(path).text
        for flag in (
            "VK_LIVE_PUBLISHING_ENABLED=true",
            "TELEGRAM_LIVE_PUBLISHING_ENABLED=true",
            "INSTAGRAM_LIVE_PUBLISHING_ENABLED=true",
            "PAYMENTS_LIVE_ENABLED=true",
        ):
            assert flag not in body, flag


def test_ui_pages_no_raw_seeded_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.vk_access_token,
        settings.vk_app_secret,
        settings.instagram_access_token,
        settings.instagram_app_secret,
        settings.telegram_bot_token,
        settings.yookassa_secret_key,
        settings.tbank_password,
    ]
    for path in ("/ui/settings", "/ui/billing", "/ui/analytics", "/ui/projects/1/dashboard"):
        body = client.get(path).text
        for secret in secrets:
            if secret:
                assert secret not in body
