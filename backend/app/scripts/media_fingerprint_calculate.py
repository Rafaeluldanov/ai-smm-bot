"""CLI расчёта fingerprint медиа (по умолчанию dry-run — без записи).

Запуск:
  make media-fingerprint-calculate project_id=1 dry_run=true
  python -m app.scripts.media_fingerprint_calculate --project-id 1 --dry-run false

Пишет fingerprint только при --dry-run false. Live/внешнего AI нет; секреты/пути не печатаются.
"""

import argparse

from app.api.deps import get_media_fingerprint_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов расчёта fingerprint."""
    parser = argparse.ArgumentParser(
        description="Рассчитать fingerprint медиа (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI расчёта fingerprint."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_fingerprint_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.calculate_project_fingerprints(
            db, args.project_id, limit=args.limit, dry_run=dry_run
        )
    if dry_run:
        print(f"DRY-RUN fingerprint: проект {summary['project_id']} (без записи)")
    else:
        print(f"Fingerprint: проект {summary['project_id']}")
        print(f"  создано записей: {summary['created']}")
    print(
        f"  просканировано: {summary['scanned']} · calculated: {summary['calculated']} · "
        f"partial: {summary['partial']}"
    )
    print("  Live-публикаций нет; внешнего AI нет.")


if __name__ == "__main__":
    main()
