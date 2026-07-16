"""CLI анализа AI Optimization Governance — v0.8.2.

Запуск:
  make governance-analyze project_id=1
  python -m app.scripts.governance_analyze --project-id 1

Заводит governance для оптимизаций проекта и считает метрики портфеля. Advisory: улучшения не
применяет, эксперименты не запускает, бизнес/KPI не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_optimization_governance_service import (
    AIOptimizationGovernanceError,
    get_ai_optimization_governance_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа governance."""
    parser = argparse.ArgumentParser(description="Анализ AI Optimization Governance")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа governance."""
    args = build_parser().parse_args()
    service = get_ai_optimization_governance_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.run_governance_cycle(db, args.project_id)
        except AIOptimizationGovernanceError as exc:
            print(f"Ошибка: {exc}")
            return
    pf = out["portfolio"]
    print(
        f"governance: всего {pf['total']} · approved {pf['approved']} · pending {pf['pending']} · "
        f"active {pf['active']} · completed {pf['completed']} · новых {len(out['created'])}"
    )
    print(f"impact: средний {pf['avg_impact_score']} · positive {pf['positive_impacts']}")
    print("governances:")
    for g in out["governances"]:
        owner = f"владелец {g['owner_user_id']}" if g["owner_user_id"] else "без владельца"
        print(
            f"  #{g['id']} опт.{g['optimization_id']} [{g['status']}/{g['approval_status']}] "
            f"{g['priority']} — {owner}"
        )
    print("insights:")
    for insight in out["insights"]:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
