"""CLI отчёта по исполнению AI Execution Coordinator — v0.7.8.

Запуск:
  make execution-report execution_plan_id=7
  python -m app.scripts.execution_report --execution-plan-id 7

Только чтение: план + цели + задачи + прогресс + блокеры + рекомендации. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_execution_coordinator_service import (
    AIExecutionCoordinatorError,
    get_ai_execution_coordinator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по исполнению."""
    parser = argparse.ArgumentParser(description="Отчёт по исполнению AI Execution Coordinator")
    parser.add_argument("--execution-plan-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по исполнению."""
    args = build_parser().parse_args()
    service = get_ai_execution_coordinator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_execution_plan(db, args.execution_plan_id)
            health = service.get_health(db, args.execution_plan_id)
        except AIExecutionCoordinatorError as exc:
            print(f"Ошибка: {exc}")
            return
    plan = bundle["plan"]
    print(f"execution_plan: {plan['id']} {plan['title']} — {plan['status']}")
    print(f"progress:       {plan['progress_percent']}%")
    print(f"objectives:     {len(bundle['objectives'])}")
    for o in bundle["objectives"]:
        print(f"  [{o['priority']}] {o['title']} ({o['status']})")
        for t in o["tasks"]:
            owner = t["owner_user_id"] if t["owner_user_id"] is not None else "нет"
            print(f"    • {t['title']} — {t['status']} (владелец: {owner})")
    print(f"blockers:       {len(health['blockers'])}")
    for b in health["blockers"]:
        print(f"  ⚠ {b['title']} — {b['detail']}")
    print("recommendations:")
    for rec in health["recommendations"]:
        print(f"  • {rec}")


if __name__ == "__main__":
    main()
