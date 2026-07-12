"""CLI одобрения задачи ревью (по умолчанию dry-run — без записи).

Запуск:
  make media-curation-review-approve task_id=1 comment="Теги корректные"
  python -m app.scripts.media_curation_review_approve --task-id 1 --comment "..." --dry-run false

Одобрение НЕ применяет изменения автоматически (нужен отдельный apply). Пишет только при
--dry-run false. Файлы не удаляются; внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_curation_review_service
from app.db.session import get_sessionmaker
from app.repositories import media_curation_repository


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов одобрения."""
    parser = argparse.ArgumentParser(description="Одобрить задачу ревью (dry-run по умолчанию)")
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--comment", default=None)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI одобрения."""
    args = build_parser().parse_args()
    dry_run = _is_true(args.dry_run)
    service = get_media_curation_review_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            task = media_curation_repository.get_task_by_id(db, args.task_id)
            if task is None:
                print(f"DRY-RUN: задача #{args.task_id} не найдена (без изменений)")
                return
            print(f"DRY-RUN одобрения: задача #{args.task_id} ({task.task_type}) — без изменений")
            print(f"  текущий review_status: {task.review_status}")
            return
        result = service.approve_task(db, args.task_id, args.comment)
        print(
            f"Задача #{args.task_id}: {result.get('outcome')} · "
            f"review_status={result.get('review_status')}"
        )
        print("  Одобрение не применяет изменения автоматически — используйте apply.")


if __name__ == "__main__":
    main()
