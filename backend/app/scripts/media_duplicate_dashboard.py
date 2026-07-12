"""CLI сводки fingerprint/дублей медиа (read-only, без записи).

Запуск:
  make media-duplicate-dashboard project_id=1
  python -m app.scripts.media_duplicate_dashboard --project-id 1

Секреты/пути к файлам не печатаются; live/внешнего AI нет; файлы не удаляются.
"""

import argparse

from app.api.deps import get_media_similarity_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки дублей."""
    parser = argparse.ArgumentParser(description="Сводка fingerprint/дублей медиа")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI сводки дублей."""
    args = build_parser().parse_args()
    service = get_media_similarity_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_duplicate_dashboard(db, args.project_id)
    print(f"Сводка дублей медиа: проект {dash['project_id']}")
    print(
        f"  fingerprint: {dash['total_fingerprints']} · точных: {dash['exact_duplicates']} · "
        f"почти: {dash['near_duplicates']} · серий: {dash['same_series']}"
    )
    print(
        f"  активных кластеров: {dash['active_clusters']} · "
        f"просмотрено: {dash['reviewed_clusters']}"
    )
    print(f"  типы кластеров: {dash['cluster_types']}")
    print(f"  fingerprint worker-ом: {dash['worker_enabled']} · live-публикаций нет")


if __name__ == "__main__":
    main()
