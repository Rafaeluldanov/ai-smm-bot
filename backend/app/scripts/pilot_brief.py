"""CLI CEO Daily Brief пилота — v1.0.0.

Запуск:
  make pilot-brief workspace_id=1
  python -m app.scripts.pilot_brief --workspace-id 1 [--user-id 5]

Печатает ежедневную сводку владельца: health, главное событие, риски, возможности, действия,
прогноз. Только чтение уже собранных данных — ничего не выполняет и бизнес не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_pilot_service import AIBusinessPilotError, PilotModeDisabledError
from app.services.ai_ceo_daily_brief_service import get_ai_ceo_daily_brief_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов Daily Brief."""
    parser = argparse.ArgumentParser(description="CEO Daily Brief пилота AI Business OS")
    parser.add_argument("--workspace-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, default=None)
    return parser


def _print_list(title: str, items: list[str]) -> None:
    print(f"\n{title}:")
    if items:
        for item in items:
            print(f"  • {item}")
    else:
        print("  —")


def main() -> None:
    """Точка входа CLI Daily Brief."""
    args = build_parser().parse_args()
    service = get_ai_ceo_daily_brief_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            brief = service.generate_daily_brief(db, args.workspace_id, user_id=args.user_id)
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"{brief['greeting']} {brief['company_name']}")
    print(f"Business Health: {brief['health_score']}/100")
    print(f"Главное событие: {brief['main_event']}")
    _print_list("Риски", brief["risks"])
    _print_list("Возможности", brief["opportunities"])
    _print_list("Действия на сегодня", brief["today_actions"])
    forecast = brief.get("forecast", {})
    if forecast.get("available"):
        print(
            f"\nПрогноз: горизонт {forecast.get('horizon')}, "
            f"уверенность {forecast.get('confidence_score')}%, риск {forecast.get('risk_level')}"
        )
    else:
        print("\nПрогноз: появится после прогона AI-цепочки.")


if __name__ == "__main__":
    main()
