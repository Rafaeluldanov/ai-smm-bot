"""CLI задач владельца AI Chief of Staff — v0.7.1.

Запуск:
  make chief-tasks project_id=1                       # список задач
  python -m app.scripts.chief_tasks --project-id 1
  python -m app.scripts.chief_tasks --task-id 5 --action accept|reject|complete

accept/complete НЕ выполняют внешних действий — лишь меняют статус задачи.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_chief_of_staff_service import (
    AIChiefOfStaffError,
    get_ai_chief_of_staff_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов задач."""
    parser = argparse.ArgumentParser(description="Задачи владельца AI Chief of Staff")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--task-id", type=int, default=None)
    parser.add_argument("--action", choices=("accept", "reject", "complete"), default=None)
    return parser


def main() -> None:
    """Точка входа CLI задач владельца."""
    args = build_parser().parse_args()
    service = get_ai_chief_of_staff_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.task_id is not None and args.action is not None:
                action = {
                    "accept": service.accept_task,
                    "reject": service.reject_task,
                    "complete": service.complete_task,
                }[args.action]
                task = action(db, args.task_id)
                print(f"task {task['id']}: {task['status']}")
                return
            if args.project_id is None:
                print("Укажите --project-id (список) или --task-id + --action")
                return
            tasks = service.list_tasks(db, args.project_id)
        except AIChiefOfStaffError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"tasks: {len(tasks)}")
    for t in tasks:
        print(
            f"  [{t['priority']}] #{t['id']} {t['title']} — {t['status']} "
            f"(score {t['priority_score']})"
        )


if __name__ == "__main__":
    main()
