"""CLI сводки курирования медиатеки (read-only, без записи).

Запуск:
  make media-curation-dashboard project_id=1
  python -m app.scripts.media_curation_dashboard --project-id 1

Секреты/пути к файлам не печатаются; файлы не удаляются; live/внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_curation_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки курирования."""
    parser = argparse.ArgumentParser(description="Сводка курирования медиатеки")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI сводки курирования."""
    args = build_parser().parse_args()
    service = get_media_curation_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_curation_dashboard(db, args.project_id, _platform(args.platform))
    print(f"Сводка курирования: проект {dash['project_id']}")
    print(
        f"  активных задач: {dash['active_tasks']} · дубли: {dash['duplicate_tasks']} · "
        f"ретег: {dash['retag_tasks']} · слабые: {dash['weak_media_tasks']}"
    )
    print(
        f"  скрыто медиа: {dash['hidden_media_count']} · "
        f"доступно в подборе: {dash['selectable_media_count']}"
    )
    print(f"  рекомендации: {dash['recommended_actions']}")
    print(f"  курирование worker-ом: {dash['worker_enabled']} · файлы не удаляются")


if __name__ == "__main__":
    main()
