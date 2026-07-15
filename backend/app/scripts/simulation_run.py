"""CLI запуска моделирования AI Strategy Simulator — v0.7.5.

Запуск:
  make simulation-run simulation_id=7
  python -m app.scripts.simulation_run --simulation-id 7

Моделирует последствия сценария на 30/60/90 дней: baseline → прогноз метрик → уверенность.
Advisory: прибыль не гарантирует, бизнес/CRM/бюджет/рекламу не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_strategy_simulator_service import (
    AIStrategySimulatorError,
    get_ai_strategy_simulator_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов запуска симуляции."""
    parser = argparse.ArgumentParser(description="Запуск моделирования AI Strategy Simulator")
    parser.add_argument("--simulation-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI запуска симуляции."""
    args = build_parser().parse_args()
    service = get_ai_strategy_simulator_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.simulate_scenario(db, args.simulation_id)
        except AIStrategySimulatorError as exc:
            print(f"Ошибка: {exc}")
            return
    sim = out["simulation"]
    print(f"simulation:     {sim['id']} ({sim['status']})")
    print(f"overall_score:  {sim['overall_score']} / 100")
    print(f"confidence:     {out['confidence']} / 100 ({sim['confidence_level']})")
    print(f"forecasts:      {len(out['forecast'])}")
    for f in out["forecast"]:
        if f["period"] != "90_days" or not f["baseline_value"]:
            continue
        print(
            f"  {f['metric']:<11} {f['baseline_value']} → {f['forecast_value']} "
            f"({f['change_percent']:+.1f}% за 90 дн, увер. {f['confidence_score']})"
        )
    print(f"note:           {out['note']}")


if __name__ == "__main__":
    main()
