"""CLI анализа AI Autonomous Optimization — v0.8.1.

Запуск:
  make optimization-analyze project_id=1
  python -m app.scripts.optimization_analyze --project-id 1

Оценивает Improvement Backlog → создаёт/оценивает оптимизации → приоритизирует. Advisory:
улучшения не применяет, бизнес/KPI не меняет; эксперименты не запускает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_optimization_engine_service import (
    AIOptimizationEngineError,
    get_ai_optimization_engine_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа оптимизации."""
    parser = argparse.ArgumentParser(description="Анализ AI Autonomous Optimization")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа оптимизации."""
    args = build_parser().parse_args()
    service = get_ai_optimization_engine_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.run_optimization_cycle(db, args.project_id)
        except AIOptimizationEngineError as exc:
            print(f"Ошибка: {exc}")
            return
    summary = out["summary"]
    print(
        f"optimizations: {summary['optimizations_total']} (open {summary['optimizations_open']}) · "
        f"новых: {len(out['created'])} · avg score {summary['avg_optimization_score']}"
    )
    print("ranking (priority):")
    for o in out["optimizations"]:
        print(
            f"  [{o['priority']}] score {o['optimization_score']} — {o['title']} "
            f"(impact {o['impact_score']}×conf {o['confidence_score']}−cost {o['cost_score']}"
            f"−risk {o['risk_score']})"
        )
    print("insights:")
    for insight in out["insights"]:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
