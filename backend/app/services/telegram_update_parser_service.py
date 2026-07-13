"""Парсер входящих Telegram-обновлений — v0.5.5.

Чистый сервис: без БД и без сети. Разбирает Telegram Update (message/callback_query/edited),
извлекает chat_id / from.id / username / text / команду и строит **санитизированную** копию
апдейта. Токен из ``/start <token>`` маскируется; сырые chat_id / from.id не попадают в
sanitized-представление (только маска). Неизвестные типы апдейтов не роняют парсер.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_KNOWN_COMMANDS = ("start", "help", "status")
# Токен привязки — base64url-подобная строка; маскируем всё после первых 6 символов.
_TOKEN_PART_RE = re.compile(r"^[A-Za-z0-9_-]{8,}$")


@dataclass
class ParsedTelegramUpdate:
    """Результат разбора Telegram Update (без сырых секретов в sanitized-полях)."""

    update_id: int | None = None
    update_type: str = "unknown"
    chat_id: str | None = None
    telegram_user_id: str | None = None
    username: str | None = None
    text: str | None = None
    command: str | None = None
    command_args: str | None = None
    is_start_command: bool = False
    start_token: str | None = None
    unknown_reason: str | None = None
    raw_sanitized: dict[str, Any] = field(default_factory=dict)


def _mask_id(value: str | None) -> str:
    """Маска id (chat/from) для sanitized-представления."""
    text = str(value or "").strip()
    if not text:
        return "—"
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}***{text[-2:]}"


def _hash_id(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:64]


def mask_start_token(text: str) -> str:
    """Замаскировать verification token в тексте ``/start <token>`` (для preview/логов)."""
    raw = str(text or "")
    parts = raw.split(maxsplit=1)
    if not parts or not parts[0].startswith("/start"):
        return raw
    if len(parts) == 1:
        return parts[0]
    token = parts[1].strip()
    if not token:
        return parts[0]
    masked = f"{token[:6]}***" if len(token) > 6 else "***"
    return f"{parts[0]} {masked}"


class TelegramUpdateParserService:
    """Разбор Telegram Update: тип/команда/ids + санитизированная копия. Чистый, без БД/сети."""

    def parse_update(self, update: dict[str, Any]) -> ParsedTelegramUpdate:
        """Разобрать апдейт в структуру ParsedTelegramUpdate (безопасно к отсутствующим полям)."""
        update = update if isinstance(update, dict) else {}
        result = ParsedTelegramUpdate()
        result.update_id = self._safe_int(update.get("update_id"))

        message, update_type = self._select_message(update)
        result.update_type = update_type
        if message is None:
            result.unknown_reason = "no supported message payload"
            result.raw_sanitized = self.sanitize_update(update)
            return result

        chat = self._as_dict(message.get("chat"))
        sender = self._as_dict(message.get("from"))
        result.chat_id = self._safe_str(chat.get("id"))
        result.telegram_user_id = self._safe_str(sender.get("id"))
        result.username = self._safe_str(sender.get("username"))
        result.text = self._safe_str(message.get("text"))

        if result.text:
            parsed_cmd = self.parse_command(result.text)
            result.command = parsed_cmd["command"]
            result.command_args = parsed_cmd["args"] or None
            result.is_start_command = parsed_cmd["command"] == "start"
            if result.is_start_command:
                result.start_token = parsed_cmd["args"] or None
        result.raw_sanitized = self.sanitize_update(update)
        return result

    def parse_command(self, text: str) -> dict[str, Any]:
        """Разобрать команду бота: ``/start <token>``, ``/start@Bot <token>``, ``/help/status``."""
        raw = str(text or "").strip()
        if not raw.startswith("/"):
            return {"command": None, "args": "", "is_command": False}
        head, _, tail = raw.partition(" ")
        # Отрезать @BotName от команды (Telegram добавляет его в группах).
        cmd = head[1:].split("@", 1)[0].lower()
        args = tail.strip()
        if cmd not in _KNOWN_COMMANDS:
            return {"command": "unknown", "args": args, "is_command": True}
        return {"command": cmd, "args": args, "is_command": True}

    def sanitize_update(self, update: dict[str, Any]) -> dict[str, Any]:
        """Собрать безопасную копию апдейта: id — только маской/hash; токен /start замаскирован."""
        update = update if isinstance(update, dict) else {}
        message, update_type = self._select_message(update)
        out: dict[str, Any] = {
            "update_id": self._safe_int(update.get("update_id")),
            "update_type": update_type,
        }
        if isinstance(message, dict):
            chat = self._as_dict(message.get("chat"))
            sender = self._as_dict(message.get("from"))
            text = self._safe_str(message.get("text"))
            out["chat"] = {
                "id_masked": _mask_id(self._safe_str(chat.get("id"))),
                "type": self._safe_str(chat.get("type")),
            }
            out["from"] = {
                "id_masked": _mask_id(self._safe_str(sender.get("id"))),
                "username": self._safe_str(sender.get("username")),
                "is_bot": bool(sender.get("is_bot")),
            }
            if text is not None:
                out["text"] = mask_start_token(text)
        return out

    def validate_update_shape(self, update: dict[str, Any]) -> dict[str, list[str]]:
        """Проверить форму апдейта: вернуть предупреждения/ошибки (без исключений)."""
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(update, dict):
            errors.append("update is not an object")
            return {"errors": errors, "warnings": warnings}
        if update.get("update_id") is None:
            warnings.append("missing update_id")
        message, update_type = self._select_message(update)
        if message is None:
            warnings.append("no supported message payload (message/edited_message/callback_query)")
        elif update_type != "callback_query":
            chat = self._as_dict(message.get("chat"))
            if not chat.get("id"):
                warnings.append("missing message.chat.id")
        return {"errors": errors, "warnings": warnings}

    # --- Внутреннее ---

    @staticmethod
    def _select_message(update: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """Выбрать полезную нагрузку и тип апдейта."""
        if isinstance(update.get("message"), dict):
            return update["message"], "message"
        if isinstance(update.get("edited_message"), dict):
            return update["edited_message"], "edited_message"
        if isinstance(update.get("callback_query"), dict):
            # callback_query — placeholder: сообщение вложено внутри.
            cq = update["callback_query"]
            inner = cq.get("message") if isinstance(cq.get("message"), dict) else {}
            merged = dict(inner)
            if isinstance(cq.get("from"), dict):
                merged["from"] = cq["from"]
            return merged, "callback_query"
        return None, "unknown"

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _safe_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


def hash_telegram_id(value: str | None) -> str | None:
    """Публичный хелпер: sha256-hash id (для лога, без раскрытия значения)."""
    return _hash_id(value)


def get_telegram_update_parser_service() -> TelegramUpdateParserService:
    """DI-фабрика парсера Telegram-апдейтов."""
    return TelegramUpdateParserService()
