"""CLI статуса процессов AI Workflow Manager — v0.7.2.

Запуск:
  make workflow-status project_id=1              # список процессов
  make workflow-status workflow_id=5             # процесс + этапы + блокеры
  python -m app.scripts.workflow_status --project-id 1
  python -m app.scripts.workflow_status --workflow-id 5

Только чтение — ничего не меняет и не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_workflow_manager_service import (
    AIWorkflowManagerError,
    get_ai_workflow_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов статуса процессов."""
    parser = argparse.ArgumentParser(description="Статус процессов AI Workflow Manager")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--workflow-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI статуса процессов."""
    args = build_parser().parse_args()
    service = get_ai_workflow_manager_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.workflow_id is not None:
                bundle = service.get_workflow(db, args.workflow_id)
                w = bundle["workflow"]
                print(f"workflow {w['id']}: {w['name']} — {w['status']} ({w['progress_percent']}%)")
                for s in bundle["steps"]:
                    print(f"  {s['order_number']}. [{s['status']}] {s['title']}")
                for b in bundle["blockers"]:
                    print(
                        f"  [blocker/{b['status']}] {b['title']} "
                        f"({b['blocker_type']}/{b['severity']})"
                    )
                return
            if args.project_id is None:
                print("Укажите --project-id (список) или --workflow-id (детали)")
                return
            workflows = service.list_workflows(db, args.project_id)
        except AIWorkflowManagerError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"workflows: {len(workflows)}")
    for w in workflows:
        print(
            f"  #{w['id']} {w['name']} — {w['status']} "
            f"({w['progress_percent']}%) [{w['workflow_type']}]"
        )


if __name__ == "__main__":
    main()
