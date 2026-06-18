"""Тесты CLI-помощников выбора тем (без запуска самих скриптов)."""

import pytest

# Импорт модулей проверяет корректность синтаксиса/импортов CLI.
from app.scripts import content_plan, select_topics
from app.scripts.select_topics import parse_business_priorities


def test_parse_single() -> None:
    assert parse_business_priorities(["футболки=100"]) == {"футболки": 100}


def test_parse_multiple() -> None:
    result = parse_business_priorities(["футболки=100", "худи=80", "шелкография=90"])
    assert result == {"футболки": 100, "худи": 80, "шелкография": 90}


def test_parse_none_and_empty() -> None:
    assert parse_business_priorities(None) == {}
    assert parse_business_priorities([]) == {}


def test_parse_invalid_format() -> None:
    with pytest.raises(ValueError):
        parse_business_priorities(["футболки"])


def test_parse_non_integer() -> None:
    with pytest.raises(ValueError):
        parse_business_priorities(["футболки=высокий"])


def test_cli_modules_have_main() -> None:
    assert callable(select_topics.main)
    assert callable(content_plan.main)
