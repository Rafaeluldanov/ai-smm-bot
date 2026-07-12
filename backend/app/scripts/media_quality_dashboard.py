"""CLI сводки качества медиа (read-only, без записи).

Запуск:
  make media-quality-dashboard project_id=1
  python -m app.scripts.media_quality_dashboard --project-id 1

Секреты/пути к файлам не печатаются; live-публикаций нет; внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_quality_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки качества."""
    parser = argparse.ArgumentParser(description="Сводка качества медиа")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI сводки качества."""
    args = build_parser().parse_args()
    service = get_media_quality_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_media_quality_dashboard(db, args.project_id, _platform(args.platform))
    print(f"Сводка качества медиа: проект {dash['project_id']}")
    print(f"  всего медиа: {dash['total_media']} · оценено: {dash['scored']}")
    print(
        f"  excellent: {dash['excellent']} · good: {dash['good']} · "
        f"weak: {dash['weak']} · дубли: {dash['duplicates']}"
    )
    print(f"  средний балл: {dash['avg_score']}")
    print(f"  частые проблемы: {dash['common_issues']}")
    print(f"  оценка worker-ом: {dash['worker_enabled']} · live-публикаций нет")


if __name__ == "__main__":
    main()
