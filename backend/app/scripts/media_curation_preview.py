"""CLI предпросмотра задач курирования медиатеки (без записи, без внешнего AI).

Запуск:
  make media-curation-preview project_id=1 limit=50
  python -m app.scripts.media_curation_preview --project-id 1 --limit 50

Файлы НЕ удаляются; теги не применяются; секреты/пути к файлам не печатаются; live нет.
"""

import argparse

from app.api.deps import get_media_curation_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра задач курирования."""
    parser = argparse.ArgumentParser(description="Предпросмотр задач курирования медиатеки")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", default=None, help="telegram|vk|instagram|all")
    parser.add_argument("--limit", type=int, default=50)
    return parser


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


def main() -> None:
    """Точка входа CLI предпросмотра задач курирования."""
    args = build_parser().parse_args()
    service = get_media_curation_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_curation_tasks(
            db, args.project_id, _platform(args.platform), limit=args.limit
        )
    print(f"Предпросмотр курирования: проект {result['project_id']} (без записи)")
    print(f"  задач найдено: {result['tasks_found']}")
    for task in result["tasks"][:6]:
        print(
            f"  {task['task_type']}: {task['title']} · conf {task['confidence_score']} · "
            f"теги {task['suggested_tags'][:3]}"
        )
    print("  Файлы не удаляются; теги применяются только после подтверждения; внешнего AI нет.")


if __name__ == "__main__":
    main()
