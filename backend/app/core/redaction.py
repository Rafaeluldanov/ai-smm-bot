"""Редакция секретов в тексте и словарях (для логов/вебхуков/диагностики).

Единый helper: замазывает токены/секреты/пароли в свободном тексте и значения под
чувствительными ключами в словарях. Реальные значения НИКОГДА не логируются целиком.
"""

from __future__ import annotations

import re
from typing import Any

_MASK = "***"

# key=value / KEY: value с чувствительным именем ключа.
_KV_KEY_RE = re.compile(
    r"(?im)\b([A-Za-z0-9_\-]*"
    r"(?:access[_-]?token|api[_-]?key|secret|password|passwd|pwd|token|signature|webhook[_-]?secret)"
    r"[A-Za-z0-9_\-]*)\s*([=:])\s*([^\s,;&\"']+)"
)
# Authorization: Bearer <...> / Authorization: <token>
_AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*:\s*)(?:bearer\s+)?([^\s,;\"']+)")
# Известные форматы токенов провайдеров.
_TOKEN_SHAPE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bvk1\.[A-Za-z0-9._-]{6,}"),  # VK user-token
    re.compile(r"\bEAA[A-Za-z0-9]{6,}"),  # Meta/Instagram graph token
    re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}"),  # Telegram bot token (<id>:<hash>)
    re.compile(r"\blive_[A-Za-z0-9]{12,}"),  # YooKassa live secret
    re.compile(r"\btest_[A-Za-z0-9]{12,}"),  # YooKassa test secret
)

# Чувствительные имена ключей в словарях (метаданные вебхуков/событий).
_SENSITIVE_DICT_KEYS = re.compile(
    r"(?i)(access[_-]?token|api[_-]?key|secret|password|passwd|pwd|token|signature|"
    r"webhook[_-]?secret|authorization|client[_-]?secret)"
)


def redact_sensitive_text(text: str) -> str:
    """Замазать секреты/токены/пароли в свободном тексте (для логов/диагностики)."""
    if not text:
        return text or ""
    out = _KV_KEY_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}", text)
    out = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}{_MASK}", out)
    for pattern in _TOKEN_SHAPE_RES:
        out = pattern.sub(_MASK, out)
    return out


def sanitize_metadata(data: Any, _depth: int = 0) -> Any:
    """Рекурсивно очистить словарь/список: значения под секретными ключами → маска.

    Строковые значения дополнительно прогоняются через ``redact_sensitive_text``.
    Ключи с чувствительными именами полностью убираются (значение не сохраняется).
    """
    if _depth > 6:
        return "***"
    if isinstance(data, dict):
        clean: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(key, str) and _SENSITIVE_DICT_KEYS.search(key):
                continue  # секретный ключ не сохраняем вовсе
            clean[key] = sanitize_metadata(value, _depth + 1)
        return clean
    if isinstance(data, (list, tuple)):
        return [sanitize_metadata(v, _depth + 1) for v in data]
    if isinstance(data, str):
        return redact_sensitive_text(data)
    return data
