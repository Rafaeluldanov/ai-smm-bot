"""CLI: экспорт аудит-лога аккаунта в JSONL/CSV (метаданные санитизированы)."""

from __future__ import annotations

import argparse
import csv
import json
from typing import Any

from app.core.redaction import sanitize_metadata
from app.db.session import get_sessionmaker
from app.repositories import audit_log_repository


def _row(entry: Any) -> dict[str, Any]:
    """Сериализовать запись аудита с повторной санитизацией метаданных."""
    return {
        "id": entry.id,
        "action": entry.action,
        "account_id": entry.account_id,
        "user_id": entry.user_id,
        "project_id": entry.project_id,
        "entity_type": entry.entity_type,
        "entity_id": entry.entity_id,
        "ip_address": entry.ip_address,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "metadata": sanitize_metadata(entry.entry_metadata or {}),
    }


def export_rows(rows: list[dict[str, Any]], output: str, fmt: str) -> None:
    """Записать строки в файл (jsonl или csv)."""
    if fmt == "csv":
        fields = [
            "id",
            "action",
            "account_id",
            "user_id",
            "project_id",
            "entity_type",
            "entity_id",
            "ip_address",
            "created_at",
            "metadata",
        ]
        with open(output, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                out = dict(row)
                out["metadata"] = json.dumps(out["metadata"], ensure_ascii=False)
                writer.writerow(out)
    else:
        with open(output, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Экспорт аудит-лога аккаунта")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    parser.add_argument("--limit", type=int, default=10000)
    return parser


def main() -> None:
    """Точка входа CLI."""
    args = build_parser().parse_args()
    with get_sessionmaker()() as db:
        entries = audit_log_repository.list_for_account(db, args.account_id, limit=args.limit)
        rows = [_row(e) for e in entries]
    export_rows(rows, args.output, args.format)
    print(f"Экспортировано записей: {len(rows)} → {args.output} ({args.format})")


if __name__ == "__main__":
    main()
