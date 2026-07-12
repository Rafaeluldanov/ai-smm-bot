"""CLI добавления комментария к задаче ревью (по умолчанию dry-run — без записи).

Запуск:
  make media-curation-review-comment task_id=1 comment="Оставить главное фото, дубль скрыть"
  python -m app.scripts.media_curation_review_comment --task-id 1 --comment "..." --dry-run false

Текст санитизируется (без секретов/путей). Пишет только при --dry-run false. Файлы не удаляются.
"""

import argparse

from app.api.deps import get_media_curation_review_service
from app.db.session import get_sessionmaker
from app.repositories import media_curation_repository
from app.services.media_curation_review_service import sanitize_review_text


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов комментария."""
    parser = argparse.ArgumentParser(
        description="Комментарий к задаче ревью (dry-run по умолчанию)"
    )
    parser.add_argument("--task-id", type=int, required=True)
    parser.add_argument("--comment", required=True)
    parser.add_argument("--dry-run", default="true", help="true|false (по умолчанию true)")
    return parser


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def main() -> None:
    """Точка входа CLI комментария."""
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
            print(f"DRY-RUN комментария к задаче #{args.task_id} (без записи):")
            print(f"  текст: {sanitize_review_text(args.comment)}")
            return
        result = service.add_comment(db, args.task_id, args.comment)
        print(f"Комментарий #{result['id']} добавлен к задаче #{args.task_id}.")
        print("  Текст санитизирован; секреты/пути не сохраняются; файлы не удаляются.")


if __name__ == "__main__":
    main()
