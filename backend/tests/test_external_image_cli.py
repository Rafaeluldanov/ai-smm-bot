"""Тесты CLI внешних изображений (импорт и парсинг аргументов)."""

from app.scripts import convert_external_image, search_external_images


def test_scripts_import() -> None:
    assert callable(search_external_images.main)
    assert callable(convert_external_image.main)


def test_search_parser() -> None:
    args = search_external_images.build_parser().parse_args(
        ["--project-slug", "teeon", "--query", "шелкография", "--limit", "5"]
    )
    assert args.project_slug == "teeon"
    assert args.query == "шелкография"
    assert args.limit == 5


def test_convert_parser() -> None:
    args = convert_external_image.build_parser().parse_args(
        ["--candidate-id", "1", "--status", "needs_license_review"]
    )
    assert args.candidate_id == 1
    assert args.status == "needs_license_review"
