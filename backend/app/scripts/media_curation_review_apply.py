"""CLI применения одобренной задачи ревью (по умолчанию dry-run — без изменений).

Запуск:
  make media-curation-review-apply task_id=1 action=approve_tags dry_run=true
  python -m app.scripts.media_curation_review_apply --task-id 1 --action approve_tags

Изменяет теги/видимость ТОЛЬКО при --dry-run false и только после approved. Файлы НЕ
удаляются; секреты/пути не печатаются; внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_curation_review_service
from app.db.session import get_sessionmaker
from app.repositories import media_curation_repository


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения."""
    parser = argparse.ArgumentParser(
        description="Применить одобренную задачу ревью (dry-run по умолчанию)"
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
    """Точка входа CLI применения."""
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
            gated = task.review_status != "approved" and args.action in (
                "approve_tags",
                "mark_duplicate",
                "hide_from_selection",
            )
            print(f"DRY-RUN применения: задача #{args.task_id} ({task.task_type}) — без изменений")
            print(
                f"  действие: {args.action} · review_status: {task.review_status}"
                + (" · будет заблокировано (нужен approved)" if gated else "")
            )
            return
        result = service.apply_approved_task(db, args.task_id, args.action)
        print(f"Задача #{args.task_id}: {result.get('outcome')} · действие {args.action}")
        print("  Изменения — только теги/видимость после approved; файлы не удаляются.")


if __name__ == "__main__":
    main()
