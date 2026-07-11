"""CLI: бесконечный цикл фонового scheduler-worker (Ctrl+C — graceful).

Пример (local, безопасно):
    PYTHONPATH=backend .venv/bin/python -m app.scripts.scheduler_worker_loop \\
        --dry-run true --force true

Отказывается стартовать, если SCHEDULER_WORKER_ENABLED=false и не передан --force true.
Даже включённый worker НЕ делает live-публикацию (только draft/needs_review). Секреты не
печатаются. В production запускать отдельным процессом/контейнером.
"""

from __future__ import annotations

import argparse
import sys

from app.services.scheduler_worker_service import SchedulerWorkerService


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Цикл scheduler-worker (без live)")
    parser.add_argument("--interval-seconds", type=int, default=None)
    parser.add_argument("--dry-run", default=None, help="true/false; по умолчанию из настроек")
    parser.add_argument("--once", default="false", help="true — один тик и выход")
    parser.add_argument("--force", default="false", help="true — запустить даже если выключен")
    parser.add_argument("--owner-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    service = SchedulerWorkerService()
    force = bool(_bool(args.force))
    summary = service.run_loop(
        once=bool(_bool(args.once)),
        dry_run=_bool(args.dry_run),
        force=force,
        owner_id=args.owner_id,
    )
    if not summary.get("ran") and not summary.get("enabled"):
        print(
            "worker выключен (SCHEDULER_WORKER_ENABLED=false). "
            "Запуск отклонён; используйте --force true."
        )
        return 0
    last = summary.get("last") or {}
    print(f"тиков выполнено: {summary.get('ticks', 0)}")
    print(
        f"последний: dry_run={last.get('dry_run')} · drafts={last.get('drafts_created')} · "
        f"scanned={last.get('targets_scanned')}"
    )
    print("live-публикация: выключена.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
