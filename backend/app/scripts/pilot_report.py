"""CLI отчёта по пилоту AI Business OS — v0.9.1.

Запуск:
  make pilot-report workspace_id=1
  python -m app.scripts.pilot_report --workspace-id 1

Формирует AI Business Pilot Report (состояние/риски/возможности/прогноз/шаги). Только чтение.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_pilot_report_service import (
    get_ai_business_pilot_report_service,
)
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по пилоту."""
    parser = argparse.ArgumentParser(description="Отчёт AI Business Pilot Report")
    parser.add_argument("--workspace-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по пилоту."""
    args = build_parser().parse_args()
    service = get_ai_business_pilot_report_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            report = service.generate_pilot_report(db, args.workspace_id)
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    print(report["title"])
    goal = report["goal"]
    print(f"Цель: выручка {goal['current_revenue']:.0f} → {goal['target_revenue']:.0f}")
    print(f"Состояние: {report['business_state']}")
    print(f"Performance Score: {report['performance_score']}/100")
    print("Риски:")
    for r in report["risks"] or ["—"]:
        print(f"  • {r}")
    print("Возможности:")
    for o in report["opportunities"] or ["—"]:
        print(f"  • {o}")
    print("AI рекомендации:")
    for a in report["ai_recommendations"] or ["—"]:
        print(f"  • {a}")
    print("Следующие шаги:")
    for s in report["next_steps"]:
        print(f"  • {s}")


if __name__ == "__main__":
    main()
