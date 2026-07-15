"""CLI генерации прогноза AI Business Forecasting Engine — v0.7.6.

Запуск:
  make forecast-generate forecast_id=7
  python -m app.scripts.forecast_generate --forecast-id 7

Строит прогноз на 3/6/12 месяцев: baseline → KPI-проекция → поправка на риск → outlook →
roadmap. Advisory: прибыль не гарантирует, бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    get_ai_business_forecasting_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов генерации прогноза."""
    parser = argparse.ArgumentParser(description="Генерация прогноза AI Business Forecasting")
    parser.add_argument("--forecast-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI генерации прогноза."""
    args = build_parser().parse_args()
    service = get_ai_business_forecasting_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.generate_business_outlook(db, args.forecast_id)
        except AIBusinessForecastingError as exc:
            print(f"Ошибка: {exc}")
            return
    f = out["forecast"]
    print(f"forecast:       {f['id']} ({f['status']}, {f['horizon']})")
    print(f"risk_level:     {f['risk_level']}")
    print(f"confidence:     {out['confidence']} / 100")
    print(f"metrics:        {len(out['metrics'])}")
    for m in out["metrics"]:
        if not m["baseline_value"]:
            continue
        print(
            f"  {m['metric']:<11} {m['baseline_value']} → {m['forecast_value']} "
            f"({m['change_percent']:+.1f}%)"
        )
    print(f"note:           {out['note']}")


if __name__ == "__main__":
    main()
