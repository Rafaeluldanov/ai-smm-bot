"""CLI памяти решений AI Chief of Staff — v0.7.1.

Запуск:
  make chief-memory project_id=1                                  # список активных решений
  python -m app.scripts.chief_memory --project-id 1
  python -m app.scripts.chief_memory --project-id 1 --decision-type restriction \\
      --key sales_style --value soft --reason "мягкие продажи"
  python -m app.scripts.chief_memory --disable 3

Память лишь ДОБАВЛЯЕТ контекст будущим рекомендациям; бизнес/CRM/бюджет не меняются.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_chief_of_staff_service import (
    AIChiefOfStaffError,
    get_ai_chief_of_staff_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов памяти решений."""
    parser = argparse.ArgumentParser(description="Память решений AI Chief of Staff")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--decision-type", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--value", default=None)
    parser.add_argument("--reason", default=None)
    parser.add_argument("--disable", type=int, default=None, help="id решения для деактивации")
    return parser


def main() -> None:
    """Точка входа CLI памяти решений."""
    args = build_parser().parse_args()
    service = get_ai_chief_of_staff_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if args.disable is not None:
                d = service.disable_decision(db, args.disable)
                print(f"decision {d['id']} ({d['key']}): active={d['active']}")
                return
            if args.project_id is None:
                print("Укажите --project-id или --disable ID")
                return
            if args.decision_type and args.key:
                d = service.save_decision_memory(
                    db,
                    args.project_id,
                    decision_type=args.decision_type,
                    key=args.key,
                    value={"value": args.value} if args.value is not None else {},
                    reason=args.reason,
                )
                print(f"saved decision {d['id']}: {d['key']} = {d['value']} ({d['decision_type']})")
                return
            decisions = service.get_decisions(db, args.project_id)
        except AIChiefOfStaffError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"decisions: {len(decisions)}")
    for d in decisions:
        print(f"  #{d['id']} [{d['decision_type']}] {d['key']} = {d['value']}")


if __name__ == "__main__":
    main()
