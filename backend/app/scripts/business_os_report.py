"""CLI отчёта по прогону AI Business OS — v0.9.0.

Запуск:
  make demo-report scenario_id=1
  python -m app.scripts.business_os_report --scenario-id 1

Формирует AI Business OS Test Report по сохранённому прогону (PASS/FAIL по этапам + score). Только
чтение — ничего не выполняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_os_demo_service import AIBusinessOSDemoError
from app.services.ai_business_os_report_service import get_ai_business_os_report_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по прогону."""
    parser = argparse.ArgumentParser(description="Отчёт AI Business OS Test Report")
    parser.add_argument("--scenario-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по прогону."""
    args = build_parser().parse_args()
    service = get_ai_business_os_report_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            report = service.generate_report(db, args.scenario_id)
        except AIBusinessOSDemoError as exc:
            print(f"Ошибка: {exc}")
            return
    print(report["title"])
    for stage in report["stages"]:
        print(f"  {stage['stage']:12} {stage['result']}")
    print(
        f"Overall Score: {report['overall_score']}/100 "
        f"({report['passed_stages']}/{report['total_stages']} PASS)"
    )
    print(f"Verdict: {report['verdict']}")


if __name__ == "__main__":
    main()
