"""Тесты UI email-шаблонов (v0.5.3). Страницы рендерятся; секретов/пароля нет; баннеры на месте."""

from fastapi.testclient import TestClient


def test_email_templates_page_renders(client: TestClient) -> None:
    r = client.get("/ui/email-templates")
    assert r.status_code == 200
    html = r.text
    assert "Email-шаблоны" in html
    # Баннер: реальная доставка выключена.
    assert "Реальная email-доставка выключена" in html


def test_email_templates_page_no_smtp_password(client: TestClient) -> None:
    html = client.get("/ui/email-templates").text
    for token in ("SMTP_PASSWORD", "smtp_password", "publish-due", "publish_due"):
        assert token not in html


def test_email_templates_page_has_safety_cards(client: TestClient) -> None:
    html = client.get("/ui/email-templates").text
    assert "SMTP live" in html
    assert "External delivery" in html


def test_delivery_page_links_email_templates(client: TestClient) -> None:
    html = client.get("/ui/notification-delivery").text
    assert "/ui/email-templates" in html


def test_digests_page_links_email_templates(client: TestClient) -> None:
    html = client.get("/ui/notification-digests").text
    assert "/ui/email-templates" in html


def test_settings_page_has_email_block(client: TestClient) -> None:
    html = client.get("/ui/settings").text
    assert "Email-уведомления" in html
    assert "/ui/email-templates" in html
    # Никаких паролей на странице настроек.
    assert "SMTP_PASSWORD" not in html and "smtp_password" not in html
