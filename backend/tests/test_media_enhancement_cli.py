"""Тесты CLI улучшения медиа: импорт скриптов и парсеры аргументов."""

from app.config import get_settings
from app.scripts import enhance_media, enhance_project_media, media_enhancement_summary
from app.services.media_enhancement_service import MediaEnhancementService


def test_enhance_media_parser() -> None:
    parser = enhance_media.build_parser()
    args = parser.parse_args(["--media-asset-id", "5", "--profile", "minimal", "--force"])
    assert args.media_asset_id == 5
    assert args.profile == "minimal"
    assert args.force is True
    assert args.no_save is False


def test_enhance_project_parser() -> None:
    parser = enhance_project_media.build_parser()
    args = parser.parse_args(["--project-slug", "teeon", "--status", "all", "--limit", "10"])
    assert args.project_slug == "teeon"
    assert args.status == "all"
    assert args.limit == 10


def test_summary_parser() -> None:
    parser = media_enhancement_summary.build_parser()
    args = parser.parse_args(["--project-slug", "teeon"])
    assert args.project_slug == "teeon"


def test_build_enhancement_service() -> None:
    service = enhance_media.build_enhancement_service(get_settings())
    assert isinstance(service, MediaEnhancementService)
