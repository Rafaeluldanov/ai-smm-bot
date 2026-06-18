"""Тесты текстовых утилит."""

from app.utils.text import normalize_whitespace, slugify, truncate


def test_normalize_whitespace() -> None:
    assert normalize_whitespace("  Привет   мир\t\nтут ") == "Привет мир тут"


def test_slugify_cyrillic() -> None:
    assert slugify("Фабрика сувениров") == "fabrika-suvenirov"
    assert slugify("TEEON") == "teeon"
    assert slugify("  Привет, мир!  ") == "privet-mir"


def test_truncate_short_text_unchanged() -> None:
    assert truncate("короткий", 50) == "короткий"


def test_truncate_long_text() -> None:
    result = truncate("очень длинный текст для обрезки", 10)
    assert len(result) <= 10
    assert result.endswith("…")
