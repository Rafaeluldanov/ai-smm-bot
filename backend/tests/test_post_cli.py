"""Тесты CLI генерации постов (импорт и парсер приоритетов)."""

from app.scripts import generate_post, generate_weekly_posts
from app.scripts.select_topics import parse_business_priorities


def test_scripts_import() -> None:
    assert callable(generate_post.main)
    assert callable(generate_weekly_posts.main)


def test_business_priority_parser() -> None:
    assert parse_business_priorities(["футболки=100", "худи=80"]) == {
        "футболки": 100,
        "худи": 80,
    }
    assert parse_business_priorities(None) == {}
