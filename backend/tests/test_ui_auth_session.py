"""Тесты UI auth/session: CSRF/refresh/logout в JS, сессии на настройках, нет токенов."""

from fastapi.testclient import TestClient


def test_shared_js_has_csrf_and_refresh_and_logout(client: TestClient) -> None:
    body = client.get("/ui/projects").text
    assert "X-CSRF-Token" in body
    assert "function csrf(" in body and "setCsrf(" in body
    assert "/auth/refresh" in body  # авто-refresh при 401
    assert "saveSession(" in body
    assert "async function logout(" in body and "/auth/logout" in body
    assert "async function logoutAll(" in body


def test_settings_page_has_sessions_and_security(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    assert "Активные сессии" in body
    assert "Выйти со всех устройств" in body
    assert "/auth/sessions" in body
    assert "security-readiness" in body
    assert "dev-токен запрещён" in body


def test_account_menu_has_sessions_link(client: TestClient) -> None:
    body = client.get("/ui/projects").text
    assert "/ui/settings#sessions" in body
    assert "Сессии" in body


def test_ui_has_no_raw_token_examples(client: TestClient) -> None:
    for path in ("/ui/login", "/ui/settings", "/ui/projects"):
        body = client.get(path).text
        # Нет «зашитых» примеров access/refresh-токенов в HTML.
        assert "eyJ" not in body  # похоже на JWT
        assert "botfleet_refresh=" not in body  # значение refresh-cookie не в HTML
