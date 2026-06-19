"""Тесты CLI sync_media: публичный режим (импорт и парсинг флага)."""

from app.scripts import sync_media


def test_script_import() -> None:
    assert callable(sync_media.main)
    assert callable(sync_media.build_parser)


def test_parse_public_flag() -> None:
    args = sync_media.build_parser().parse_args(["--project-slug", "teeon", "--public"])
    assert args.project_slug == "teeon"
    assert args.public is True


def test_parse_defaults_to_private() -> None:
    args = sync_media.build_parser().parse_args(["--project-slug", "teeon"])
    assert args.public is False
