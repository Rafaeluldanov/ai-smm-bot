"""CLI предпросмотра кластеров дублей медиа (без записи, без удаления).

Запуск:
  make media-duplicate-preview project_id=1
  python -m app.scripts.media_duplicate_preview --project-id 1

Файлы НЕ удаляются; секреты/пути к файлам не печатаются; live/внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_similarity_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра кластеров дублей."""
    parser = argparse.ArgumentParser(description="Предпросмотр кластеров дублей медиа")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра кластеров дублей."""
    args = build_parser().parse_args()
    service = get_media_similarity_service()
    factory = get_sessionmaker()
    with factory() as db:
        summary = service.find_duplicate_clusters(db, args.project_id, dry_run=True)
    print(f"Предпросмотр дублей: проект {summary['project_id']} (без записи)")
    print(f"  найдено кластеров: {summary['clusters_found']}")
    for cluster in summary["clusters"][:5]:
        print(
            f"  тип {cluster['cluster_type']} · similarity {cluster['similarity_score']} · "
            f"canonical #{cluster['canonical_media_asset_id']} · "
            f"медиа {cluster['member_media_asset_ids']}"
        )
    print("  Файлы не удаляются; внешнего AI нет; live-публикаций нет.")


if __name__ == "__main__":
    main()
