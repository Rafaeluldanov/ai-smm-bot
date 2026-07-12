"""Парсер упоминаний (@mentions) — v0.5.0.

Извлекает из текста комментария упоминания трёх форматов и резолвит их в пользователя
СТРОГО в пределах того же аккаунта. Внешнего поиска нет; нерезолвленные упоминания
допустимы (основное действие не падает).

Поддерживаемые форматы:
- ``@email@example.com`` — по email;
- ``@username`` — по local-part email или slug полного имени;
- ``@user_id:123`` — по внутреннему id (только в пределах аккаунта).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.repositories import account_repository, user_repository

if TYPE_CHECKING:
    from app.models.user import User

# @user_id:123 | @email@host.tld | @username (unicode word chars, точки/дефисы).
_MENTION_RE = re.compile(
    r"@(user_id:\d+|[\w.+-]+@[\w-]+\.[\w.-]+|[^\W\d_][\w.\-]*)",
    re.UNICODE,
)

# Транслитерация кириллицы для сопоставления username по имени (latin slug).
_TRANSLIT = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "e",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "h",
    "ц": "c",
    "ч": "ch",
    "ш": "sh",
    "щ": "sch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}


def extract_mentions(text: str) -> list[str]:
    """Извлечь список упоминаний (без ведущего @), сохраняя порядок и убирая дубли."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for match in _MENTION_RE.finditer(text):
        value = match.group(1).strip().rstrip(".")
        key = value.lower()
        if value and key not in seen:
            seen.add(key)
            out.append(value)
    return out


def normalize_mention(value: str) -> str:
    """Нормализовать упоминание к нижнему регистру без ведущего @/пробелов."""
    return str(value or "").strip().lstrip("@").strip().lower()


def _slug(value: str) -> str:
    lowered = str(value or "").strip().lower()
    out = "".join(_TRANSLIT.get(ch, ch) for ch in lowered)
    return re.sub(r"[^a-z0-9]+", "", out)


def _handles_for_user(user: User) -> set[str]:
    handles: set[str] = set()
    local = (user.email or "").split("@", 1)[0].strip().lower()
    if local:
        handles.add(local)
        handles.add(_slug(local))
    if user.full_name:
        handles.add(_slug(user.full_name))
        handles.add(user.full_name.strip().lower().replace(" ", ""))
    return {h for h in handles if h}


def _account_user_ids(db: Session, account_id: int) -> set[int]:
    account = account_repository.get_account_by_id(db, account_id)
    if account is None:
        return set()
    ids = {account.owner_user_id}
    for membership in account_repository.list_memberships_for_account(db, account_id):
        if membership.status == "active":
            ids.add(membership.user_id)
    return ids


def resolve_mention_to_user(db: Session, account_id: int | None, mention: str) -> User | None:
    """Резолвить упоминание в пользователя СТРОГО в пределах аккаунта (иначе None)."""
    if account_id is None:
        return None  # без аккаунта не резолвим (legacy/seed) — остаётся unresolved
    value = normalize_mention(mention)
    if not value:
        return None
    account_users = _account_user_ids(db, account_id)
    if not account_users:
        return None

    # @user_id:123
    if value.startswith("user_id:"):
        try:
            uid = int(value.split(":", 1)[1])
        except (ValueError, IndexError):
            return None
        user = user_repository.get_user_by_id(db, uid)
        if user is not None and user.is_active and user.id in account_users:
            return user
        return None

    # @email@host.tld
    if "@" in value:
        user = user_repository.get_user_by_email(db, value)
        if user is not None and user.is_active and user.id in account_users:
            return user
        return None

    # @username → по handle пользователя в пределах аккаунта
    target = _slug(value) or value
    for uid in account_users:
        user = user_repository.get_user_by_id(db, uid)
        if user is None or not user.is_active:
            continue
        handles = _handles_for_user(user)
        if value in handles or target in handles:
            return user
    return None
