"""CLI: preview due-задач расписания (без записи, без списания, без live-публикации).

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.schedule_due_preview \\
        --account-id 1 --project-id 1 --platform telegram --date today

Печатает: сколько due-задач, что было бы создано, сколько units нужно, предупреждения.
Секреты/токены не печатаются.
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import get_sessionmaker
from app.services.schedule_automation_service import (
    ScheduleAutomationError,
    ScheduleAutomationService,
)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preview due-задач расписания (без записи)")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None)
    parser.add_argument("--date", default="today")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    service = ScheduleAutomationService()
    with get_sessionmaker()() as db:
        try:
            result = service.preview_due_runs(
                db,
                account_id=args.account_id,
                project_id=args.project_id,
                date_arg=args.date,
                platform_key=args.platform,
            )
        except ScheduleAutomationError as exc:
            print(f"Ошибка: {exc}")
            return 2
    print(f"дата: {result['run_date']} · due-задач: {result['due_count']}")
    print(
        f"units нужно: {result['total_units']} · баланс: {result['balance_units']} · "
        f"хватает: {'да' if result['affordable'] else 'нет'}"
    )
    for entry in result["entries"]:
        print(
            f"  - {entry['platform_key']} {entry['planned_time']} → {entry['outcome']} "
            f"(units {entry['estimated_units']}, media {entry['media_count']}, "
            f"creds {entry['credentials_source']})"
        )
    print("live-публикация: выключена (создаются только draft/needs_review).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
