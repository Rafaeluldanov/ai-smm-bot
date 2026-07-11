"""CLI: пометить просроченные публичные media-ссылки как expired (+ опц. чистка кэша).

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.media_proxy_cleanup --dry-run true

По умолчанию dry-run (ничего не меняет) — только показывает, сколько ссылок истекло.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models.public_media_link import PublicMediaLink
from app.repositories import public_media_link_repository


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Очистка просроченных media-ссылок")
    parser.add_argument("--dry-run", default="true", help="true (по умолчанию) — не менять БД")
    return parser


def _count_expired(db: Session, now: datetime) -> int:
    stmt = select(PublicMediaLink).where(
        PublicMediaLink.status == "active",
        PublicMediaLink.expires_at.is_not(None),
        PublicMediaLink.expires_at < now,
    )
    return len(list(db.scalars(stmt).all()))


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    dry_run = _bool(args.dry_run)
    now = datetime.now(UTC)
    with get_sessionmaker()() as db:
        if dry_run:
            count = _count_expired(db, now)
            print(f"dry-run: просроченных активных ссылок — {count} (БД не изменена)")
        else:
            count = public_media_link_repository.cleanup_expired(db, now)
            print(f"помечено expired: {count}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
