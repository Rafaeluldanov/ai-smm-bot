"""CLI создания плана исполнения AI Execution Coordinator — v0.7.8.

Запуск:
  make execution-create project_id=1 strategic_plan_id=5
  python -m app.scripts.execution_create --project-id 1 --strategic-plan-id 5

Создаёт план исполнения из УТВЕРЖДЁННОГО стратегического плана (status=draft). Advisory:
генерацию не запускает, задачи не выполняет, бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_execution_coordinator_service import (
    AIExecutionCoordinatorError,
    get_ai_execution_coordinator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания плана исполнения."""
    parser = argparse.ArgumentParser(description="Создание плана AI Execution Coordinator")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--strategic-plan-id", type=int, required=True)
    parser.add_argument("--title", default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания плана исполнения."""
    args = build_parser().parse_args()
    service = get_ai_execution_coordinator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            plan = service.create_execution_plan(
                db,
                args.project_id,
                strategic_plan_id=args.strategic_plan_id,
                title=args.title,
            )
        except AIExecutionCoordinatorError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"execution_plan: {plan['id']} ({plan['status']})")
    print(f"title:          {plan['title']}")
    print(f"strategic_plan: {plan['strategic_plan_id']}")


if __name__ == "__main__":
    main()
