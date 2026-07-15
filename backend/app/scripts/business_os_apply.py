"""CLI применения бизнес-действия Autonomous Business OS — v0.7.0.

Запуск:
  make business-os-apply project_id=1 action_id=5
  python -m app.scripts.business_os_apply --action-id 5

Одобряет (если нужно) и применяет действие с подтверждением APPLY_BUSINESS_ACTION.
Меняет только draft-стратегию/кампанию — НЕ live/CRM/бюджет/публикации.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_executive_service import (
    APPLY_CONFIRMATION,
    AIExecutiveError,
    get_ai_executive_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов применения бизнес-действия."""
    parser = argparse.ArgumentParser(description="Применение бизнес-действия Business OS")
    parser.add_argument("--action-id", type=int, required=True)
    parser.add_argument("--no-accept", action="store_true", help="не одобрять автоматически")
    return parser


def main() -> None:
    """Точка входа CLI применения бизнес-действия."""
    args = build_parser().parse_args()
    service = get_ai_executive_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if not args.no_accept:
                service.accept_action(db, args.action_id)
            result = service.apply_action(db, args.action_id, confirmation=APPLY_CONFIRMATION)
        except AIExecutiveError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"applied:        {result['applied']}")
    print(f"live_enabled:   {result['live_enabled']}")
    print(f"note:           {result['note']}")


if __name__ == "__main__":
    main()
