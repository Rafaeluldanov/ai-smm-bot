"""CLI генерации стратегического плана AI Business Planner — v0.7.7.

Запуск:
  make plan-generate goal_id=5
  python -m app.scripts.plan_generate --goal-id 5

Строит план: gap → стратегия → кварталы → KPI → вехи. Advisory: план не выполняет,
бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_planner_service import (
    AIBusinessPlannerError,
    get_ai_business_planner_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации плана."""
    parser = argparse.ArgumentParser(description="Генерация плана AI Business Planner")
    parser.add_argument("--goal-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI генерации плана."""
    args = build_parser().parse_args()
    service = get_ai_business_planner_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.generate_strategic_plan(db, args.goal_id)
        except AIBusinessPlannerError as exc:
            print(f"Ошибка: {exc}")
            return
    plan = out["plan"]
    gap = plan["gap_analysis"]
    print(f"plan_id:        {plan['id']} ({plan['status']})")
    print(f"gap:            {gap.get('current')} → {gap.get('target')} (gap {gap.get('gap')})")
    print(f"confidence:     {plan['confidence_score']} / 100")
    print(f"strategy:       {plan['strategy'].get('approach')}")
    print(f"objectives:     {len(out['objectives'])}")
    for o in out["objectives"]:
        kpi = (o["kpi"] or [{}])[0]
        print(
            f"  [{o['quarter']}] {o['title']} — {kpi.get('metric')} ≈ {kpi.get('quarter_target')} "
            f"({o['priority']})"
        )
    print("note:           План — рекомендация, выполняется только после одобрения.")


if __name__ == "__main__":
    main()
