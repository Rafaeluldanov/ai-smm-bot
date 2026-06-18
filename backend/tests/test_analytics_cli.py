"""Тесты CLI аналитики (импорт и парсинг аргументов)."""

from app.scripts import analytics_report, ingest_analytics


def test_scripts_import() -> None:
    assert callable(ingest_analytics.main)
    assert callable(analytics_report.main)


def test_ingest_parser() -> None:
    args = ingest_analytics.build_parser().parse_args(
        ["--post-id", "1", "--platform", "telegram", "--impressions", "1000", "--clicks", "20"]
    )
    assert args.post_id == 1
    assert args.platform == "telegram"
    assert args.impressions == 1000
    assert args.clicks == 20


def test_report_parser() -> None:
    args = analytics_report.build_parser().parse_args(
        ["--project-slug", "teeon", "--type", "clusters"]
    )
    assert args.project_slug == "teeon"
    assert args.type == "clusters"
    assert "feedback" in analytics_report.REPORT_TYPES
