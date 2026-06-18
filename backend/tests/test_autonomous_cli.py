"""Тесты CLI автономного режима (импорт и парсинг аргументов)."""

from app.scripts import autonomous_report, autonomous_run


def test_scripts_import() -> None:
    assert callable(autonomous_run.main)
    assert callable(autonomous_report.main)


def test_run_parser_and_request() -> None:
    args = autonomous_run.build_parser().parse_args(
        [
            "--project-slug",
            "teeon",
            "--mode",
            "auto_schedule",
            "--business-priority",
            "футболки=100",
            "--allow-auto-schedule",
        ]
    )
    assert args.project_slug == "teeon"
    assert args.mode == "auto_schedule"
    assert args.allow_auto_schedule is True

    request = autonomous_run.build_request(args)
    assert request.project_slug == "teeon"
    assert request.mode == "auto_schedule"
    assert request.business_priorities == {"футболки": 100}
    assert request.settings is not None
    assert request.settings.allow_auto_schedule is True


def test_run_parser_dry_run_forces_mode() -> None:
    args = autonomous_run.build_parser().parse_args(["--project-slug", "teeon", "--dry-run"])
    request = autonomous_run.build_request(args)
    assert request.mode == "dry_run"


def test_report_parser() -> None:
    args = autonomous_report.build_parser().parse_args(["--run-id", "1"])
    assert args.run_id == 1
