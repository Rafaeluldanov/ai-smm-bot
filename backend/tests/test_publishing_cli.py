"""Тесты CLI автопостинга (импорт и парсинг аргументов)."""

from datetime import datetime

from app.scripts import publish_due, publish_post, schedule_post


def test_scripts_import() -> None:
    assert callable(schedule_post.main)
    assert callable(publish_post.main)
    assert callable(publish_due.main)


def test_parse_datetime() -> None:
    assert schedule_post.parse_datetime("2026-06-18T12:00:00") == datetime(2026, 6, 18, 12, 0, 0)
    assert schedule_post.parse_datetime(None) is None


def test_schedule_parser_platforms() -> None:
    args = schedule_post.build_parser().parse_args(
        ["--post-id", "1", "--platform", "telegram", "--platform", "vk"]
    )
    assert args.post_id == 1
    assert args.platform == ["telegram", "vk"]


def test_publish_parser_force() -> None:
    args = publish_post.build_parser().parse_args(["--post-id", "2", "--force"])
    assert args.post_id == 2
    assert args.force is True


def test_publish_parser_dry_run() -> None:
    args = publish_post.build_parser().parse_args(["--post-id", "3", "--dry-run"])
    assert args.post_id == 3
    assert args.dry_run is True
    assert args.force is False
