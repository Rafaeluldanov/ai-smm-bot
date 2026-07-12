"""CLI оценки качества медиа (по умолчанию dry-run — без записи).

Запуск:
  make media-quality-score project_id=1 platform=telegram dry_run=true
  python -m app.scripts.media_quality_score --project-id 1 --platform telegram --dry-run false

Пишет снимки только при --dry-run false. Live-публикаций нет; внешнего AI нет; секреты не
печатаются.
"""

import argparse

from app.api.deps import get_media_quality_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов оценки качества."""
    parser = argparse.ArgumentParser(
        description="Оценить качество медиа проекта (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI оценки качества."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_quality_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.score_project_media(
            db, args.project_id, _platform(args.platform), limit=args.limit, dry_run=dry_run
        )
    if dry_run:
        print(f"DRY-RUN оценки качества: проект {summary['project_id']} (без записи)")
    else:
        print(f"Оценка качества: проект {summary['project_id']}")
        print(f"  снимков создано: {summary['snapshots_created']}")
    print(
        f"  оценено: {summary['scored']} · weak: {summary['weak']} · дубли: {summary['duplicates']}"
    )
    print("  Live-публикаций нет; внешнего AI нет.")


if __name__ == "__main__":
    main()
