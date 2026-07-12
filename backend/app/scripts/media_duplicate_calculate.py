"""CLI построения кластеров дублей медиа (по умолчанию dry-run — без записи).

Запуск:
  make media-duplicate-calculate project_id=1 dry_run=true
  python -m app.scripts.media_duplicate_calculate --project-id 1 --dry-run false

Пишет кластеры только при --dry-run false. Файлы НЕ удаляются; секреты/пути не печатаются.
"""

import argparse

from app.api.deps import get_media_similarity_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов построения кластеров дублей."""
    parser = argparse.ArgumentParser(
        description="Построить кластеры дублей медиа (dry-run по умолчанию)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI построения кластеров дублей."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_similarity_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.find_duplicate_clusters(db, args.project_id, dry_run=dry_run)
    if dry_run:
        print(f"DRY-RUN дублей: проект {summary['project_id']} (без записи)")
        print(f"  найдено кластеров: {summary['clusters_found']}")
    else:
        print(f"Кластеры дублей: проект {summary['project_id']}")
        print(f"  создано кластеров: {summary['clusters_created']}")
    print("  Файлы не удаляются; внешнего AI нет; live-публикаций нет.")


if __name__ == "__main__":
    main()
