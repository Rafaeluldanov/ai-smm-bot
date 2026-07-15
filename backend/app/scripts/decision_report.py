"""CLI отчёта по решению AI Decision Engine — v0.7.4.

Запуск:
  make decision-report decision_id=5
  python -m app.scripts.decision_report --decision-id 5

Только чтение: решение + сценарии + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_decision_engine_service import (
    AIDecisionEngineError,
    get_ai_decision_engine_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по решению."""
    parser = argparse.ArgumentParser(description="Отчёт по решению AI Decision Engine")
    parser.add_argument("--decision-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по решению."""
    args = build_parser().parse_args()
    service = get_ai_decision_engine_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_decision(db, args.decision_id)
            explanation = service.explain_decision(db, args.decision_id)
        except AIDecisionEngineError as exc:
            print(f"Ошибка: {exc}")
            return
    d = bundle["decision"]
    print(f"decision:       {d['id']} {d['title']} — {d['status']} ({d['decision_type']})")
    print(f"confidence:     {d['confidence_score']} / 100")
    print(f"recommended:    scenario #{d['recommended_scenario_id'] or '—'}")
    print(f"scenarios:      {len(bundle['scenarios'])}")
    for s in bundle["scenarios"]:
        print(f"  [{s['status']}] {s['title']} — score {s['expected_impact'].get('score')}")
    print(f"signals:        {len(bundle['signals'])}")
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
