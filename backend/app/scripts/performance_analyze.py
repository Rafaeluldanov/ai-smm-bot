"""CLI анализа эффективности AI Performance Intelligence — v0.7.9.

Запуск:
  make performance-analyze project_id=1
  python -m app.scripts.performance_analyze --project-id 1

Собирает снимок эффективности: факт vs план → score → отклонения → рекомендации. Advisory:
планы/KPI/бизнес не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_performance_intelligence_service import (
    AIPerformanceIntelligenceError,
    get_ai_performance_intelligence_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа эффективности."""
    parser = argparse.ArgumentParser(description="Анализ эффективности AI Performance Intelligence")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа эффективности."""
    args = build_parser().parse_args()
    service = get_ai_performance_intelligence_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.create_snapshot(db, args.project_id)
        except AIPerformanceIntelligenceError as exc:
            print(f"Ошибка: {exc}")
            return
    snap = out["snapshot"]
    print(f"snapshot:       {snap['id']} ({snap['status']})")
    print(f"score:          {snap['performance_score']} / 100")
    print(f"metrics:        {len(out['metrics'])}")
    for m in out["metrics"]:
        print(
            f"  {m['metric']:<11} план {m['target_value']} / факт {m['actual_value']} "
            f"({m['difference_percent']:+.1f}%, {m['status']})"
        )
    print(f"deviations:     {len(out['deviations'])}")
    print(f"recommendations:{len(out['recommendations'])}")
    print("note:           Измерение и рекомендации; планы/бизнес не меняются.")


if __name__ == "__main__":
    main()
