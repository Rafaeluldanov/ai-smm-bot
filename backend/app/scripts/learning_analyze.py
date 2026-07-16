"""CLI анализа цикла обучения AI Continuous Improvement — v0.8.0.

Запуск:
  make learning-analyze project_id=1
  python -m app.scripts.learning_analyze --project-id 1

Прогоняет цикл обучения: опыт → события → паттерны → улучшения. Advisory: бизнес/стратегию/KPI
не меняет, улучшения не применяет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_continuous_improvement_service import (
    AIContinuousImprovementError,
    get_ai_continuous_improvement_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа обучения."""
    parser = argparse.ArgumentParser(description="Анализ цикла обучения AI Continuous Improvement")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа цикла обучения."""
    args = build_parser().parse_args()
    service = get_ai_continuous_improvement_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.run_learning_cycle(db, args.project_id)
        except AIContinuousImprovementError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"experiences:    {len(out['experiences'])}")
    for e in out["experiences"]:
        print(f"  [{e['experience_type']}] {e['title']} → {e['outcome']}")
    print(f"patterns:       {len(out['patterns'])}")
    for p in out["patterns"]:
        print(f"  [{p['pattern_type']}] {p['title']} (увер. {p['confidence_score']})")
    print(f"improvements:   {len(out['improvements'])}")
    for i in out["improvements"]:
        print(f"  [{i['priority']}] {i['title']}")
    print("insights:")
    for insight in out["insights"]:
        print(f"  • {insight}")


if __name__ == "__main__":
    main()
