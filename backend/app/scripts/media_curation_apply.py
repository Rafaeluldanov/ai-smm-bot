"""CLI применения задачи курирования (по умолчанию dry-run — без изменений).

Запуск:
  make media-curation-apply task_id=1 action=approve_tags dry_run=true
  python -m app.scripts.media_curation_apply --task-id 1 --action approve_tags --dry-run false

Меняет теги/видимость ТОЛЬКО при --dry-run false. Файлы НЕ удаляются; секреты не печатаются.
"""

import argparse

from app.api.deps import get_media_curation_service
from app.db.session import get_sessionmaker
from app.repositories import media_curation_repository


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения задачи."""
    parser = argparse.ArgumentParser(
        description="Применить задачу курирования (dry-run по умолчанию)"
    )
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument(
        "--action",
        default="mark_reviewed",
        help="approve_tags|mark_duplicate|hide_from_selection|restore_to_selection|"
        "ignore_cluster|mark_reviewed",
    )
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI применения задачи."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_curation_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            task = media_curation_repository.get_task_by_id(db, args.task_id)
            if task is None:
                print(f"DRY-RUN: задача #{args.task_id} не найдена (без изменений)")
                return
            print(f"DRY-RUN применения: задача #{args.task_id} ({task.task_type}) — без изменений")
            print(f"  действие: {args.action} · статус: {task.status}")
            return
        result = service.apply_task(db, args.task_id, args.action)
        print(f"Задача #{args.task_id}: {result.get('outcome')} · действие {args.action}")
        print("  Файлы не удаляются; изменения — только теги/видимость; внешнего AI нет.")


if __name__ == "__main__":
    main()
