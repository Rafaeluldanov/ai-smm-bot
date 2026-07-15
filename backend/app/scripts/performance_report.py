"""CLI отчёта по эффективности AI Performance Intelligence — v0.7.9.

Запуск:
  make performance-report snapshot_id=7
  python -m app.scripts.performance_report --snapshot-id 7

Только чтение: снимок + метрики + отклонения + рекомендации + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_performance_intelligence_service import (
    AIPerformanceIntelligenceError,
    get_ai_performance_intelligence_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по эффективности."""
    parser = argparse.ArgumentParser(
        description="Отчёт по эффективности AI Performance Intelligence"
    )
    parser.add_argument("--snapshot-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по эффективности."""
    args = build_parser().parse_args()
    service = get_ai_performance_intelligence_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_snapshot(db, args.snapshot_id)
            explanation = service.explain_performance(db, args.snapshot_id)
        except AIPerformanceIntelligenceError as exc:
            print(f"Ошибка: {exc}")
            return
    snap = bundle["snapshot"]
    print(f"snapshot:       {snap['id']} — {snap['status']}")
    print(f"score:          {snap['performance_score']} / 100")
    print(f"metrics:        {len(bundle['metrics'])}")
    for m in bundle["metrics"]:
        print(
            f"  {m['metric']:<11} план {m['target_value']} / факт {m['actual_value']} "
            f"({m['difference_percent']:+.1f}%, {m['status']})"
        )
    print("deviations:")
    for d in bundle["deviations"]:
        print(f"  ⚠ [{d['impact']}] {d['title']}")
    print("recommendations:")
    for r in bundle["recommendations"]:
        print(f"  • [{r['priority']}] {r['title']}")
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
