"""Тесты парсера Telegram-апдейтов (v0.5.5). Чистый; без БД/сети; безопасен к пустым полям."""

from app.services.telegram_update_parser_service import (
    TelegramUpdateParserService,
    mask_start_token,
)


def _svc() -> TelegramUpdateParserService:
    return TelegramUpdateParserService()


def test_parse_start_token() -> None:
    u = {
        "update_id": 10,
        "message": {
            "text": "/start ABC123token456",
            "chat": {"id": 987654321, "type": "private"},
            "from": {"id": 555, "username": "ivan"},
        },
    }
    r = _svc().parse_update(u)
    assert r.update_type == "message"
    assert r.command == "start"
    assert r.is_start_command is True
    assert r.start_token == "ABC123token456"
    assert r.chat_id == "987654321"
    assert r.telegram_user_id == "555"
    assert r.username == "ivan"


def test_parse_start_at_botname() -> None:
    parsed = _svc().parse_command("/start@BotfleetBot MYTOKEN99")
    assert parsed["command"] == "start"
    assert parsed["args"] == "MYTOKEN99"


def test_parse_help_and_status() -> None:
    assert _svc().parse_command("/help")["command"] == "help"
    assert _svc().parse_command("/status")["command"] == "status"


def test_unknown_command() -> None:
    assert _svc().parse_command("/foobar arg")["command"] == "unknown"
    assert _svc().parse_command("plain text")["command"] is None


def test_unknown_update_ignored_no_crash() -> None:
    r = _svc().parse_update({"update_id": 1, "my_chat_member": {}})
    assert r.update_type == "unknown"
    assert r.unknown_reason is not None


def test_missing_fields_safe() -> None:
    r = _svc().parse_update({})
    assert r.update_type == "unknown"
    r2 = _svc().parse_update({"message": {}})
    assert r2.chat_id is None
    # validate_update_shape не бросает исключений.
    warnings = _svc().validate_update_shape({})
    assert "warnings" in warnings and isinstance(warnings["warnings"], list)


def test_start_token_masked_in_sanitized() -> None:
    u = {
        "update_id": 5,
        "message": {
            "text": "/start supersecrettoken123",
            "chat": {"id": 123456789},
            "from": {"id": 42, "username": "bob"},
        },
    }
    r = _svc().parse_update(u)
    blob = str(r.raw_sanitized)
    assert "supersecrettoken123" not in blob
    assert r.raw_sanitized["text"] == "/start supers***"


def test_chat_and_from_id_masked_in_sanitized() -> None:
    u = {
        "update_id": 7,
        "message": {"text": "hi", "chat": {"id": 987654321}, "from": {"id": 111222333}},
    }
    r = _svc().parse_update(u)
    blob = str(r.raw_sanitized)
    assert "987654321" not in blob
    assert "111222333" not in blob
    assert "***" in r.raw_sanitized["chat"]["id_masked"]


def test_mask_start_token_helper() -> None:
    assert mask_start_token("/start abcdef123456") == "/start abcdef***"
    assert mask_start_token("/help") == "/help"
    assert mask_start_token("/start") == "/start"


def test_callback_query_type() -> None:
    u = {
        "update_id": 9,
        "callback_query": {
            "from": {"id": 5, "username": "u"},
            "message": {"chat": {"id": 999}},
            "data": "btn",
        },
    }
    r = _svc().parse_update(u)
    assert r.update_type == "callback_query"
