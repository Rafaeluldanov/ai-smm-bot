"""Тесты CLI согласования постов (импорт и парсинг аргументов)."""

import pytest

from app.scripts import review_post


def test_script_import() -> None:
    assert callable(review_post.main)
    assert callable(review_post.parse_review_args)
    assert "submit" in review_post.REVIEW_ACTIONS


def test_parse_review_args() -> None:
    args = review_post.parse_review_args(
        ["--post-id", "1", "--action", "submit", "--actor-name", "Stanislav"]
    )
    assert args.post_id == 1
    assert args.action == "submit"
    assert args.actor_name == "Stanislav"
    assert args.actor_role == "manager"


def test_parse_review_args_invalid_action() -> None:
    with pytest.raises(SystemExit):
        review_post.parse_review_args(["--post-id", "1", "--action", "bogus"])
