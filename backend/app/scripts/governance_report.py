"""CLI отчёта AI Optimization Governance — v0.8.2.

Запуск:
  make governance-report project_id=1
  python -m app.scripts.governance_report --project-id 1

Только чтение: governance-записи + метрики портфеля + выводы. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_optimization_governance_service import (
    AIOptimizationGovernanceError,
    get_ai_optimization_governance_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по governance."""
    parser = argparse.ArgumentParser(description="Отчёт AI Optimization Governance")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по governance."""
    args = build_parser().parse_args()
    service = get_ai_optimization_governance_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            governances = service.get_governances(db, args.project_id)
            portfolio = service.calculate_portfolio_metrics(db, args.project_id)
            insights = service.explain_governance(db, args.project_id)["insights"]
        except AIOptimizationGovernanceError as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"portfolio: всего {portfolio['total']} · approved {portfolio['approved']} · "
        f"active {portfolio['active']} · completed {portfolio['completed']} · "
        f"impact {portfolio['avg_impact_score']} (positive {portfolio['positive_impacts']})"
    )
    print("governances:")
    for g in governances:
        owner = f"владелец {g['owner_user_id']}" if g["owner_user_id"] else "без владельца"
        print(
            f"  #{g['id']} опт.{g['optimization_id']} [{g['status']}/{g['approval_status']}] "
            f"{g['priority']} — {owner}"
        )
    print("insights:")
    for insight in insights:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
