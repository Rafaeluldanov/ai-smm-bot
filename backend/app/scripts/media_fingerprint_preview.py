"""CLI предпросмотра fingerprint медиа (без записи, без внешнего AI/сети).

Запуск:
  make media-fingerprint-preview project_id=1 limit=50
  python -m app.scripts.media_fingerprint_preview --project-id 1 --limit 50

Live-публикаций нет; fingerprint не пишутся; секреты/пути к файлам не печатаются.
"""

import argparse

from app.api.deps import get_media_fingerprint_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра fingerprint."""
    parser = argparse.ArgumentParser(description="Предпросмотр fingerprint медиа")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--limit", type=int, default=50)
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра fingerprint."""
    args = build_parser().parse_args()
    service = get_media_fingerprint_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.calculate_project_fingerprints(
            db, args.project_id, limit=args.limit, dry_run=True
        )
    print(f"Предпросмотр fingerprint: проект {summary['project_id']} (без записи)")
    print(
        f"  просканировано: {summary['scanned']} · calculated: {summary['calculated']} · "
        f"partial: {summary['partial']} · unavailable: {summary['unavailable']}"
    )
    for row in summary["results"][:5]:
        print(
            f"  медиа #{row['media_asset_id']}: {row['status']} · источник {row['source']} · "
            f"hash {row.get('file_sha256_prefix') or '—'}"
        )
    print("  Live-публикаций нет; внешнего AI нет.")


if __name__ == "__main__":
    main()
