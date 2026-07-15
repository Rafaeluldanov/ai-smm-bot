"""CLI отчёта по прогнозу AI Business Forecasting Engine — v0.7.6.

Запуск:
  make forecast-report forecast_id=7
  python -m app.scripts.forecast_report --forecast-id 7

Только чтение: прогноз + KPI + roadmap + объяснение. Ничего не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    get_ai_business_forecasting_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов отчёта по прогнозу."""
    parser = argparse.ArgumentParser(description="Отчёт по прогнозу AI Business Forecasting")
    parser.add_argument("--forecast-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI отчёта по прогнозу."""
    args = build_parser().parse_args()
    service = get_ai_business_forecasting_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            bundle = service.get_forecast(db, args.forecast_id)
            explanation = service.explain_forecast(db, args.forecast_id)
        except AIBusinessForecastingError as exc:
            print(f"Ошибка: {exc}")
            return
    f = bundle["forecast"]
    print(f"forecast:       {f['id']} {f['title']} — {f['status']} ({f['horizon']})")
    print(f"risk_level:     {f['risk_level']}")
    print(f"confidence:     {f['confidence_score']} / 100")
    print(f"metrics:        {len(bundle['metrics'])}")
    for m in bundle["metrics"]:
        print(
            f"  {m['metric']:<11} {m['baseline_value']} → {m['forecast_value']} "
            f"({m['change_percent']:+.1f}%)"
        )
    roadmap = bundle["roadmap"]
    if roadmap is not None:
        print("roadmap:")
        for q in roadmap["quarters"]:
            print(f"  [{q.get('quarter')}] {q.get('focus')}: {', '.join(q.get('goals', []))}")
    print("why:")
    for reason in explanation["reasons"]:
        print(f"  • {reason}")


if __name__ == "__main__":
    main()
