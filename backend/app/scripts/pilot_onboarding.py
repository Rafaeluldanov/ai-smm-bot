"""CLI онбординга компании в бизнес-пилот — v1.0.0.

Запуск:
  make pilot-onboarding account_id=1
  python -m app.scripts.pilot_onboarding --account-id 1 [--company-name "TEEON Pilot"] [--user-id 5]

Заводит пилот компании одним шагом: workspace → profile → goal(s) → KPI(s) (демо 5М→10М).
Только advisory: AI ничего не выполняет и бизнес не меняет. Если --user-id не задан — берём
владельца аккаунта (member-check fail-closed требует участника).
"""

import argparse

from app.db.session import get_sessionmaker
from app.repositories import account_repository
from app.services.ai_business_pilot_service import AIBusinessPilotError, PilotModeDisabledError
from app.services.ai_pilot_onboarding_service import get_ai_pilot_onboarding_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов онбординга пилота."""
    parser = argparse.ArgumentParser(description="Онбординг компании в бизнес-пилот AI Business OS")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--company-name", default="TEEON Pilot")
    parser.add_argument("--industry", default="apparel")
    parser.add_argument("--user-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI онбординга пилота."""
    args = build_parser().parse_args()
    service = get_ai_pilot_onboarding_service()
    factory = get_sessionmaker()
    with factory() as db:
        user_id = args.user_id
        if user_id is None:
            account = account_repository.get_account_by_id(db, args.account_id)
            if account is None:
                print(f"Ошибка: аккаунт id={args.account_id} не найден")
                return
            user_id = account.owner_user_id
        try:
            pilot = service.create_company_pilot(
                db,
                args.account_id,
                company_name=args.company_name,
                industry=args.industry,
                user_id=user_id,
            )
        except (AIBusinessPilotError, PilotModeDisabledError) as exc:
            print(f"Ошибка: {exc}")
            return
    ws = pilot["workspace"]
    profile = pilot["profile"]
    print(f"pilot workspace #{ws['id']}: {ws['company_name']} ({ws['status']})")
    print(
        f"profile #{profile['id']}: выручка {profile['current_revenue']:.0f} → "
        f"{profile['target_revenue']:.0f}"
    )
    for goal in pilot["goals"]:
        print(
            f"goal #{goal['id']}: {goal['title']} "
            f"({goal['current_value']:.0f}/{goal['target_value']:.0f} {goal['unit']})"
        )
    for kpi in pilot["kpis"]:
        print(
            f"kpi #{kpi['id']}: {kpi['name']} "
            f"({kpi['current_value']:.0f}/{kpi['target_value']:.0f} {kpi['unit']})"
        )


if __name__ == "__main__":
    main()
