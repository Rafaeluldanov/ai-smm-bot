"""Тесты безопасных проверок подключения (offline + httpx.MockTransport, без реальной сети)."""

import httpx

from app.services.platform_connection_check_service import (
    ConnectionCheckInput,
    PlatformConnectionCheckService,
)

SVC = PlatformConnectionCheckService()
_TG_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _client(handler) -> httpx.Client:  # noqa: ANN001
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json(data, code=200) -> httpx.Response:  # noqa: ANN001
    return httpx.Response(code, json=data)


def test_telegram_check_ok_with_mock() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/getMe"):
            return _json({"ok": True, "result": {"id": 42, "username": "bot"}})
        if path.endswith("/getChat"):
            return _json({"ok": True, "result": {"id": -100, "title": "Channel"}})
        if path.endswith("/getChatMember"):
            return _json({"ok": True, "result": {"status": "administrator"}})
        return _json({"ok": False}, 404)

    data = ConnectionCheckInput("telegram", token=_TG_TOKEN, external_id="@teeon")
    with _client(handler) as client:
        result = SVC.check_telegram(data, client)
    assert result.status == "ok"
    assert result.ok is True
    keys = {c.key for c in result.checks}
    assert {"getMe", "getChat", "getChatMember"} <= keys


def test_telegram_chat_not_found_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getMe"):
            return _json({"ok": True, "result": {"id": 42}})
        if request.url.path.endswith("/getChat"):
            return _json({"ok": False, "description": "Bad Request: chat not found"})
        return _json({"ok": False}, 404)

    data = ConnectionCheckInput("telegram", token=_TG_TOKEN, external_id="@missing")
    with _client(handler) as client:
        result = SVC.check_telegram(data, client)
    assert result.status == "error"
    chat = next(c for c in result.checks if c.key == "getChat")
    assert "chat not found" in chat.message.lower()


def test_vk_user_token_recognized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("groups.getById"):
            return _json({"response": [{"id": 1, "name": "Group"}]})
        if path.endswith("users.get"):
            return _json({"response": [{"id": 7}]})
        if path.endswith("groups.get"):
            return _json({"response": {"count": 2}})
        return _json({"error": {"error_code": 1}})

    data = ConnectionCheckInput("vk", token="vk1.usertoken", external_id="123")
    with _client(handler) as client:
        result = SVC.check_vk(data, client)
    token_type = next(c for c in result.checks if c.key == "token_type")
    assert token_type.ok is True


def test_vk_error_27_explained() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"error": {"error_code": 27, "error_msg": "Group authorization failed"}})

    data = ConnectionCheckInput("vk", token="communitytoken", external_id="123")
    with _client(handler) as client:
        result = SVC.check_vk(data, client)
    assert result.status == "error"
    assert any("27" in c.message for c in result.checks)


def test_instagram_check_requires_id_and_token() -> None:
    # Без токена/id — офлайн-ошибка, без сети.
    result = SVC.check_instagram(ConnectionCheckInput("instagram"))
    assert result.status == "error"

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"id": "178", "username": "brand"})

    data = ConnectionCheckInput("instagram", token="tok", external_id="178")
    with _client(handler) as client:
        result = SVC.check_instagram(data, client)
    profile = next(c for c in result.checks if c.key == "profile")
    assert profile.ok is True


def test_yandex_public_url_validation() -> None:
    bad = SVC.check_yandex_disk(ConnectionCheckInput("yandex_disk", url="ftp://x"))
    assert bad.status in ("error", "warning")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    data = ConnectionCheckInput("yandex_disk", url="https://disk.yandex.ru/d/abc")
    with _client(handler) as client:
        result = SVC.check_yandex_disk(data, client)
    reach = next(c for c in result.checks if c.key == "reachable")
    assert reach.ok is True


def test_planned_platform_status() -> None:
    result = SVC.check_planned("tiktok")
    assert result.status == "planned"
    assert result.ok is False


def test_offline_default_no_network() -> None:
    # Без http_client проверки не ходят в сеть — валидируют наличие полей.
    result = SVC.check_telegram(ConnectionCheckInput("telegram", token=_TG_TOKEN, external_id="@x"))
    assert result.status in ("ok", "warning")
    assert any(c.key == "online" for c in result.checks)
