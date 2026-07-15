"""CLI создания стратегической симуляции AI Strategy Simulator — v0.7.5.

Запуск:
  make simulation-create project_id=1 scenario_id=5 period=90_days
  python -m app.scripts.simulation_create --project-id 1 --scenario-id 5 --period 90_days

Создаёт симуляцию из сценария решения (status=generated). Advisory: моделирование не запускает,
бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    get_ai_strategy_simulator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания симуляции."""
    parser = argparse.ArgumentParser(description="Создание симуляции AI Strategy Simulator")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--scenario-id", type=int, required=True)
    parser.add_argument("--title", default=None)
    parser.add_argument("--objective", default=None)
    parser.add_argument("--period", dest="period", default="90_days")
    return parser


def main() -> None:
    """Точка входа CLI создания симуляции."""
    args = build_parser().parse_args()
    service = get_ai_strategy_simulator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            simulation = service.create_simulation(
                db,
                args.project_id,
                scenario_id=args.scenario_id,
                title=args.title,
                objective=args.objective,
                simulation_period=args.period,
            )
        except AIStrategySimulatorError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"simulation_id:  {simulation['id']} ({simulation['status']})")
    print(f"title:          {simulation['title']}")
    print(f"scenario_id:    {simulation['scenario_id']}")
    print(f"period:         {simulation['simulation_period']}")
    print("note:           Прогноз — модельная оценка, не финансовая гарантия.")


if __name__ == "__main__":
    main()
