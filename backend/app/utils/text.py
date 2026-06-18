"""Утилиты для работы с текстом."""

import re

# Транслитерация кириллицы в латиницу для slug-ов.
_TRANSLIT: dict[str, str] = {
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
    "й": "i",
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

_MULTIDASH = re.compile(r"-+")


def normalize_whitespace(text: str) -> str:
    """Свернуть любые последовательности пробельных символов в один пробел."""
    return " ".join(text.split())


def slugify(text: str) -> str:
    """Преобразовать строку (в т. ч. кириллицу) в URL-совместимый slug.

    >>> slugify("Фабрика сувениров")
    'fabrika-suvenirov'
    >>> slugify("TEEON")
    'teeon'
    """
    chars: list[str] = []
    for char in text.lower().strip():
        if char in _TRANSLIT:
            chars.append(_TRANSLIT[char])
        elif char.isascii() and char.isalnum():
            chars.append(char)
        else:
            chars.append("-")
    slug = _MULTIDASH.sub("-", "".join(chars)).strip("-")
    return slug


def truncate(text: str, max_length: int, suffix: str = "…") -> str:
    """Обрезать текст до ``max_length`` символов, добавив суффикс при обрезке."""
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    if len(suffix) >= max_length:
        return suffix[:max_length]
    return text[: max_length - len(suffix)].rstrip() + suffix
