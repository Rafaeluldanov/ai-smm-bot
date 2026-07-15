"""CLI создания процесса AI Workflow Manager — v0.7.2.

Запуск:
  make workflow-create project_id=1 name="Рост продаж" type=sales [goal="увеличить продажи"]
  python -m app.scripts.workflow_create --project-id 1 --name "Рост продаж" --type sales

Создаёт процесс и сразу генерирует этапы. Advisory: ничего не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_workflow_manager_service import (
    AIWorkflowManagerError,
    get_ai_workflow_manager_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания процесса."""
    parser = argparse.ArgumentParser(description="Создание процесса AI Workflow Manager")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--type", dest="workflow_type", default="custom")
    parser.add_argument("--goal", default=None)
    parser.add_argument("--no-steps", action="store_true", help="не генерировать этапы")
    return parser


def main() -> None:
    """Точка входа CLI создания процесса."""
    args = build_parser().parse_args()
    service = get_ai_workflow_manager_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            workflow = service.create_workflow_from_goal(
                db,
                args.project_id,
                name=args.name,
                workflow_type=args.workflow_type,
                goal=args.goal,
                status="active",
            )
            steps = [] if args.no_steps else service.generate_workflow_steps(db, workflow["id"])
        except AIWorkflowManagerError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"workflow_id:    {workflow['id']} ({workflow['workflow_type']}, {workflow['status']})")
    print(f"name:           {workflow['name']}")
    print(f"goal:           {workflow['goal'] or '—'}")
    print(f"steps:          {len(steps)} создано")
    for s in steps:
        print(f"  {s['order_number']}. [{s['priority']}] {s['title']}")


if __name__ == "__main__":
    main()
