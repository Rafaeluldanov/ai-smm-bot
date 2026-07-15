"""CLI создания прогноза AI Business Forecasting Engine — v0.7.6.

Запуск:
  make forecast-create project_id=1 horizon=12_months
  python -m app.scripts.forecast_create --project-id 1 --horizon 12_months

Создаёт прогноз из текущего состояния бизнеса (status=generated). Advisory: проекцию не
запускает, бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_forecasting_service import (
    AIBusinessForecastingError,
    get_ai_business_forecasting_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания прогноза."""
    parser = argparse.ArgumentParser(description="Создание прогноза AI Business Forecasting")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--horizon", default="12_months")
    parser.add_argument("--title", default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания прогноза."""
    args = build_parser().parse_args()
    service = get_ai_business_forecasting_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            forecast = service.create_forecast(
                db, args.project_id, horizon=args.horizon, title=args.title
            )
        except AIBusinessForecastingError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"forecast_id:    {forecast['id']} ({forecast['status']})")
    print(f"title:          {forecast['title']}")
    print(f"horizon:        {forecast['horizon']}")
    print("note:           Прогноз — модельная оценка, не финансовая гарантия.")


if __name__ == "__main__":
    main()
