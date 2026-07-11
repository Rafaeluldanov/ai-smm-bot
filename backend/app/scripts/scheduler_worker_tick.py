"""CLI: один тик фонового scheduler-worker (безопасно, без live-публикации).

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.scheduler_worker_tick \\
        --dry-run true --force true

dry-run true (по умолчанию) — только preview/log, без создания постов. dry-run false —
создаёт draft/needs_review (если SCHEDULER_WORKER_CREATE_DRAFTS=true), НЕ live. Секреты
не печатаются.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from app.db.session import get_sessionmaker
from app.services.scheduler_worker_service import SchedulerWorkerService


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Один тик scheduler-worker (без live)")
    parser.add_argument("--dry-run", default="true", help="true (по умолчанию) — без записи")
    parser.add_argument(
        "--force", default="false", help="true — запустить даже если worker выключен"
    )
    parser.add_argument("--platform", default=None)
    parser.add_argument("--account-id", type=int, default=None)
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--now", default=None, help="ISO-время (для тестов due-слотов)")
    parser.add_argument("--owner-id", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else None
    service = SchedulerWorkerService()
    with get_sessionmaker()() as db:
        result = service.tick(
            db,
            owner_id=args.owner_id,
            now=now,
            dry_run=_bool(args.dry_run),
            force=_bool(args.force),
            platform_key=args.platform,
            account_id=args.account_id,
            project_id=args.project_id,
        )
    print(f"enabled: {result.enabled} · dry_run: {result.dry_run} · lease: {result.lease_acquired}")
    print(
        f"targets scanned/processed: {result.targets_scanned}/{result.targets_processed} · "
        f"drafts: {result.drafts_created} · runs: {result.schedule_runs_created}"
    )
    print(
        f"skipped: {result.skipped} · failed: {result.failed} · "
        f"insufficient_balance: {result.insufficient_balance} · "
        f"missing_credentials: {result.missing_credentials}"
    )
    for err in result.errors:
        print(f"warning: {err}")
    print("live-публикация: выключена (только draft/needs_review).")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
