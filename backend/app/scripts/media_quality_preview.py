"""CLI предпросмотра оценки качества медиа (без записи, без внешнего AI).

Запуск:
  make media-quality-preview project_id=1 platform=telegram limit=50
  python -m app.scripts.media_quality_preview --project-id 1 --platform telegram --limit 50

Live-публикаций нет; снимки не пишутся; секреты/пути к файлам не печатаются.
"""

import argparse

from app.api.deps import get_media_quality_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра оценки качества."""
    parser = argparse.ArgumentParser(description="Предпросмотр оценки качества медиа")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--limit", type=int, default=50)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI предпросмотра оценки качества."""
    args = build_parser().parse_args()
    service = get_media_quality_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.score_project_media(
            db, args.project_id, _platform(args.platform), limit=args.limit, dry_run=True
        )
    print(f"Предпросмотр качества медиа: проект {summary['project_id']} (без записи)")
    print(f"  просканировано: {summary['scanned']} · оценено: {summary['scored']}")
    print(
        f"  excellent: {summary['excellent']} · good: {summary['good']} · "
        f"weak: {summary['weak']} · дубли: {summary['duplicates']}"
    )
    for row in summary["results"][:5]:
        print(
            f"  медиа #{row['media_asset_id']}: {row['status']} · балл {row['overall_score']} "
            f"· проблемы: {row['issue_codes'][:3]}"
        )
    print("  Live-публикаций нет; внешнего AI нет.")


if __name__ == "__main__":
    main()
