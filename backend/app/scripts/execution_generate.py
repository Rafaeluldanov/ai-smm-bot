"""CLI генерации исполнения AI Execution Coordinator — v0.7.8.

Запуск:
  make execution-generate execution_plan_id=7
  python -m app.scripts.execution_generate --execution-plan-id 7

Строит исполнение: цели (из quarter objectives) → задачи → прогресс. Advisory: задачи не
выполняет, бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_execution_coordinator_service import (
    AIExecutionCoordinatorError,
    get_ai_execution_coordinator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации исполнения."""
    parser = argparse.ArgumentParser(description="Генерация исполнения AI Execution Coordinator")
    parser.add_argument("--execution-plan-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI генерации исполнения."""
    args = build_parser().parse_args()
    service = get_ai_execution_coordinator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.generate_execution(db, args.execution_plan_id)
        except AIExecutionCoordinatorError as exc:
            print(f"Ошибка: {exc}")
            return
    plan = out["plan"]
    health = out["health"]
    print(f"execution_plan: {plan['id']} ({plan['status']})")
    print(f"progress:       {plan['progress_percent']}%")
    print(f"objectives:     {len(out['objectives'])}")
    for o in out["objectives"]:
        print(f"  [{o['priority']}] {o['title']} — задач: {len(o['tasks'])}")
    print(f"blockers:       {len(health['blockers'])}")
    print("note:           Координация — совет; задачи не выполняются автоматически.")


if __name__ == "__main__":
    main()
