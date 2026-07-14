"""CLI старта клиентского онбординга — v0.6.4.

Запуск:
  make onboarding-start user_id=1 company="TEEON"
  python -m app.scripts.onboarding_start --user-id 1 --company "TEEON"

Создаёт аккаунт/проект/сессию онбординга (или возвращает активную). Live не включает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.client_onboarding_service import get_client_onboarding_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов старта онбординга."""
    parser = argparse.ArgumentParser(description="Старт клиентского онбординга")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--company", type=str, default=None)
    return parser


def main() -> None:
    """Точка входа CLI старта онбординга."""
    args = build_parser().parse_args()
    service = get_client_onboarding_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.start_onboarding(db, args.user_id, company_name=args.company)
    print(f"session_id:   {result['session_id']}")
    print(f"project_id:   {result['project_id']}")
    print(f"current_step: {result['current_step']}")
    print(f"resumed:      {result['resumed']}")
    print("Онбординг начат. Live-публикация НЕ включена.")


if __name__ == "__main__":
    main()
