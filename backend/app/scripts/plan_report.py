"""CLI отчёта по стратегическому плану AI Business Planner — v0.7.7.

Запуск:
  make plan-report plan_id=7
  python -m app.scripts.plan_report --plan-id 7

Только чтение: план + квартальные цели + вехи + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_planner_service import (
    AIBusinessPlannerError,
    get_ai_business_planner_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по плану."""
    parser = argparse.ArgumentParser(description="Отчёт по плану AI Business Planner")
    parser.add_argument("--plan-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по плану."""
    args = build_parser().parse_args()
    service = get_ai_business_planner_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_plan(db, args.plan_id)
            explanation = service.explain_plan(db, args.plan_id)
        except AIBusinessPlannerError as exc:
            print(f"Ошибка: {exc}")
            return
    plan = bundle["plan"]
    print(f"plan:           {plan['id']} {plan['title']} — {plan['status']}")
    print(f"confidence:     {plan['confidence_score']} / 100")
    print(f"objectives:     {len(bundle['objectives'])}")
    for o in bundle["objectives"]:
        print(f"  [{o['quarter']}] {o['title']} ({o['priority']}, {o['status']})")
        for m in o["milestones"]:
            print(f"    ◦ {m['title']}")
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
