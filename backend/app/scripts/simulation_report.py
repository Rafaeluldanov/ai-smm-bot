"""CLI отчёта по симуляции AI Strategy Simulator — v0.7.5.

Запуск:
  make simulation-report simulation_id=7
  python -m app.scripts.simulation_report --simulation-id 7

Только чтение: симуляция + прогнозы + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    get_ai_strategy_simulator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по симуляции."""
    parser = argparse.ArgumentParser(description="Отчёт по симуляции AI Strategy Simulator")
    parser.add_argument("--simulation-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по симуляции."""
    args = build_parser().parse_args()
    service = get_ai_strategy_simulator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_simulation(db, args.simulation_id)
            explanation = service.explain_forecast(db, args.simulation_id)
        except AIStrategySimulatorError as exc:
            print(f"Ошибка: {exc}")
            return
    sim = bundle["simulation"]
    print(f"simulation:     {sim['id']} {sim['title']} — {sim['status']}")
    print(f"overall_score:  {sim['overall_score']} / 100 ({sim['confidence_level']})")
    print(f"period:         {sim['simulation_period']}")
    print(f"forecasts:      {len(bundle['forecast'])}")
    for f in bundle["forecast"]:
        print(
            f"  [{f['period']}] {f['metric']:<11} {f['baseline_value']} → {f['forecast_value']} "
            f"({f['change_percent']:+.1f}%, увер. {f['confidence_score']})"
        )
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
