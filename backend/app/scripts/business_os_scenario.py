"""CLI прогона demo-сценария AI Business OS — v0.9.0.

Запуск:
  make demo-run workspace_id=1 scenario=growth
  python -m app.scripts.business_os_scenario --workspace-id 1 --scenario growth

Прогоняет AI-цепочку на demo-проекте, печатает PASS/FAIL по этапам + score. Только advisory;
бизнес/CRM/workflow не затрагиваются.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_os_demo_service import AIBusinessOSDemoError
from app.services.ai_business_os_scenario_service import get_ai_business_os_scenario_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов прогона сценария."""
    parser = argparse.ArgumentParser(description="Прогон demo-сценария AI Business OS")
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument(
        "--scenario", choices=["growth", "recovery", "optimization"], default="growth"
    )
    return parser


def main() -> None:
    """Точка входа CLI прогона сценария."""
    args = build_parser().parse_args()
    service = get_ai_business_os_scenario_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            scenario = service.run_scenario(db, args.workspace_id, args.scenario)
        except AIBusinessOSDemoError as exc:
            print(f"Ошибка: {exc}")
            return
    result = scenario["result_data"]
    print(
        f"scenario #{scenario['id']} [{scenario['scenario_type']}] "
        f"{scenario['status']} — score {scenario['score']}/100"
    )
    for stage in result.get("stages", []):
        mark = "✓" if stage["status"] == "pass" else "✗"
        print(f"  {mark} {stage['stage']:12} {stage['status'].upper():5} :: {stage['detail']}")


if __name__ == "__main__":
    main()
