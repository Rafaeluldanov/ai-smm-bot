"""CLI прогона pilot-сценария AI Business OS — v0.9.1.

Запуск:
  make pilot-run workspace_id=1
  python -m app.scripts.pilot_run --workspace-id 1

Прогоняет всю AI-цепочку на pilot-проекте (advisory) и печатает PASS/FAIL по этапам + score.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_pilot_scenario_service import (
    get_ai_business_pilot_scenario_service,
)
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов прогона пилота."""
    parser = argparse.ArgumentParser(description="Прогон pilot-сценария AI Business OS")
    parser.add_argument("--workspace-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI прогона пилота."""
    args = build_parser().parse_args()
    service = get_ai_business_pilot_scenario_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            run = service.run_growth_pilot(db, args.workspace_id)
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"pilot run [{run['scenario']}] {run['status']} — score {run['score']}/100")
    for stage in run.get("stages", []):
        mark = "✓" if stage["status"] == "pass" else "✗"
        print(f"  {mark} {stage['stage']:12} {stage['status'].upper():5} :: {stage['detail']}")


if __name__ == "__main__":
    main()
