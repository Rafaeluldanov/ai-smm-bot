"""CLI: обработать due-задачи расписания. По умолчанию dry-run (без записи).

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.schedule_due_run \\
        --account-id 1 --project-id 1 --platform telegram --date today --dry-run true

dry-run true (по умолчанию) — только preview, без записи и списания. dry-run false —
создаёт draft/needs_review посты (НЕ live). Секреты/токены не печатаются.
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import get_sessionmaker
from app.services.schedule_automation_service import (
    ScheduleAutomationError,
    ScheduleAutomationService,
)


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Обработать due-задачи расписания")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None)
    parser.add_argument("--date", default="today")
    parser.add_argument("--dry-run", default="true", help="true (по умолчанию) — без записи")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    dry_run = _bool(args.dry_run)
    service = ScheduleAutomationService()
    with get_sessionmaker()() as db:
        try:
            if dry_run:
                result = service.run_due_dry(
                    db, args.account_id, args.project_id, args.date, None, args.platform
                )
            else:
                result = service.run_due(
                    db, args.account_id, args.project_id, args.date, None, args.platform
                )
        except ScheduleAutomationError as exc:
            print(f"Ошибка: {exc}")
            return 2
    mode = "dry-run (без записи)" if dry_run else "run (создаёт draft/needs_review)"
    print(f"режим: {mode} · дата: {result['run_date']} · due-задач: {result['due_count']}")
    if dry_run:
        print(f"units нужно: {result['total_units']} · баланс: {result['balance_units']}")
        for entry in result["entries"]:
            print(f"  - {entry['platform_key']} {entry['planned_time']} → {entry['outcome']}")
    else:
        print(f"создано drafts: {result['created']} · пропущено: {result['skipped']}")
        for entry in result["entries"]:
            outcome = entry.get("outcome") or entry.get("status")
            units = entry.get("units_charged", 0)
            print(f"  - {entry.get('platform_key', '')} → {outcome} (units {units})")
    print("live-публикация: выключена.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
