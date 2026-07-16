"""CLI создания pilot-воркспейса AI Business OS — v0.9.1.

Запуск:
  make pilot-create account_id=1
  python -m app.scripts.pilot_create --account-id 1 [--company-name "TEEON Pilot"]

Создаёт pilot-воркспейс + бизнес-профиль (демо-значения 5М→10М). Только advisory; бизнес не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    PilotModeDisabledError,
    get_ai_business_pilot_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания пилота."""
    parser = argparse.ArgumentParser(description="Создание pilot-воркспейса AI Business OS")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--company-name", default="TEEON Pilot")
    return parser


def main() -> None:
    """Точка входа CLI создания пилота."""
    args = build_parser().parse_args()
    service = get_ai_business_pilot_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            workspace = service.create_pilot_workspace(
                db, args.account_id, company_name=args.company_name, industry="apparel"
            )
            profile = service.create_business_profile(
                db, workspace["id"], current_revenue=5_000_000, target_revenue=10_000_000
            )
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"pilot workspace #{workspace['id']}: {workspace['company_name']} ({workspace['status']})"
    )
    print(
        f"profile #{profile['id']}: выручка {profile['current_revenue']:.0f} → "
        f"{profile['target_revenue']:.0f}"
    )


if __name__ == "__main__":
    main()
