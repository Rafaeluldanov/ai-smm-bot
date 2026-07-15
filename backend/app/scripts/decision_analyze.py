"""CLI анализа решения AI Decision Engine — v0.7.4.

Запуск:
  make decision-analyze decision_id=5
  python -m app.scripts.decision_analyze --decision-id 5

Собирает сигналы, строит сценарии, оценивает и рекомендует лучший. Ничего не применяет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_decision_engine_service import (
    AIDecisionEngineError,
    get_ai_decision_engine_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов анализа решения."""
    parser = argparse.ArgumentParser(description="Анализ решения AI Decision Engine")
    parser.add_argument("--decision-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI анализа решения."""
    args = build_parser().parse_args()
    service = get_ai_decision_engine_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.analyze_decision(db, args.decision_id)
        except AIDecisionEngineError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"decision:       {out['decision']['id']} ({out['decision']['status']})")
    print(f"scenarios:      {len(out['scenarios'])}")
    for s in out["scenarios"]:
        im = s["expected_impact"]
        ra = s["risk_analysis"]
        print(
            f"  [{s['status']}] {s['title']} — score {im.get('score')} "
            f"(эффект {im.get('impact')}, риск {ra.get('risk')})"
        )
    rec = out["recommendation"]
    if rec["scenario"]:
        print(f"recommendation: «{rec['scenario']['title']}» — score {rec['score']}")
        print(f"reason:         {rec['reason']}")


if __name__ == "__main__":
    main()
