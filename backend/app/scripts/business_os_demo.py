"""CLI создания demo-компании AI Business OS — v0.9.0.

Запуск:
  make demo-create account_id=1
  python -m app.scripts.business_os_demo --account-id 1

Создаёт demo-воркспейс TEEON. Только demo-данные; реальных сущностей не создаёт.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_os_demo_service import (
    AIBusinessOSDemoError,
    get_ai_business_os_demo_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания demo-компании."""
    parser = argparse.ArgumentParser(description="Создание demo-компании AI Business OS")
    parser.add_argument("--account-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI создания demo-компании."""
    args = build_parser().parse_args()
    service = get_ai_business_os_demo_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            workspace = service.create_demo_company(db, args.account_id)
            goal = service.create_demo_goal()
        except AIBusinessOSDemoError as exc:
            print(f"Ошибка: {exc}")
            return
    print(
        f"demo workspace #{workspace['id']}: {workspace['company_name']} ({workspace['industry']})"
    )
    print(f"goal: {goal['title']} ({goal['current_value']:.0f} → {goal['target_value']:.0f})")


if __name__ == "__main__":
    main()
