"""CLI статуса клиентского онбординга — v0.6.4.

Запуск:
  make onboarding-status session_id=1
  python -m app.scripts.onboarding_status --session-id 1

Показывает прогресс сессии онбординга. Секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.client_onboarding_service import (
    ClientOnboardingError,
    get_client_onboarding_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов статуса онбординга."""
    parser = argparse.ArgumentParser(description="Статус клиентского онбординга")
    parser.add_argument("--session-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI статуса онбординга."""
    args = build_parser().parse_args()
    service = get_client_onboarding_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            d = service.get_session(db, args.session_id)
        except ClientOnboardingError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"status:            {d['status']}")
    print(f"current_step:      {d['current_step']}")
    print(f"completion:        {d['completion_percent']}%")
    print(f"project_id:        {d['project_id']}")
    for step in d.get("steps", []):
        print(f"  [{step['status']}] {step['step_name']}")


if __name__ == "__main__":
    main()
