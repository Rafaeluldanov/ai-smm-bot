"""CLI отчёта AI Autonomous Optimization — v0.8.1.

Запуск:
  make optimization-report project_id=1
  python -m app.scripts.optimization_report --project-id 1

Только чтение: ранжированные оптимизации + эксперименты + выводы. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.repositories import optimization_repository as repo
from app.services.ai_optimization_engine_service import (
    AIOptimizationEngineError,
    get_ai_optimization_engine_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по оптимизации."""
    parser = argparse.ArgumentParser(description="Отчёт AI Autonomous Optimization")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по оптимизации."""
    args = build_parser().parse_args()
    service = get_ai_optimization_engine_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            optimizations = service.get_optimizations(db, args.project_id)
            insights = service.explain_optimization(db, args.project_id)["insights"]
            summary = repo.build_optimization_summary(db, args.project_id)
            experiments = [
                repo.public_experiment_view(e)
                for e in repo.list_experiments_for_project(db, args.project_id)
            ]
        except AIOptimizationEngineError as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"optimizations: {summary['optimizations_total']} (open {summary['optimizations_open']}) · "
        f"experiments: {summary['experiments_total']} "
        f"(completed {summary['experiments_completed']}) · "
        f"avg score {summary['avg_optimization_score']}"
    )
    print("optimizations:")
    for o in optimizations:
        print(f"  [{o['priority']}/{o['status']}] score {o['optimization_score']} — {o['title']}")
    print("experiments:")
    for e in experiments:
        print(
            f"  #{e['id']} [{e['status']}] {e['metric']}: "
            f"{e['baseline_value']} → {e['target_value']}"
        )
    print("insights:")
    for insight in insights:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
