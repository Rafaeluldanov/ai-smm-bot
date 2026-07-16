"""CLI отчёта по обучению AI Continuous Improvement — v0.8.0.

Запуск:
  make learning-report project_id=1
  python -m app.scripts.learning_report --project-id 1

Только чтение: история опыта + паттерны + backlog улучшений + выводы. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_continuous_improvement_service import (
    AIContinuousImprovementError,
    get_ai_continuous_improvement_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по обучению."""
    parser = argparse.ArgumentParser(description="Отчёт по обучению AI Continuous Improvement")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по обучению."""
    args = build_parser().parse_args()
    service = get_ai_continuous_improvement_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            history = service.get_history(db, args.project_id)
            patterns = service.get_patterns(db, args.project_id)
            improvements = service.get_improvements(db, args.project_id)
            insights = service.explain_learning(db, args.project_id)["insights"]
        except AIContinuousImprovementError as exc:
            print(f"Ошибка: {exc}")
            return
    summary = history["summary"]
    print(
        f"experiences: {summary['experiences_total']} · patterns: {summary['patterns_total']} · "
        f"improvements: {summary['improvements_total']} (open {summary['improvements_open']})"
    )
    print("patterns:")
    for p in patterns:
        print(f"  [{p['pattern_type']}] {p['title']} (увер. {p['confidence_score']})")
    print("improvements:")
    for i in improvements:
        print(f"  [{i['priority']}/{i['status']}] {i['title']}")
    print("insights:")
    for insight in insights:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
