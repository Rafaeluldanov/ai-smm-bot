"""CLI создания решения AI Decision Engine — v0.7.4.

Запуск:
  make decision-create project_id=1 type=efficiency title="Низкая конверсия"
  python -m app.scripts.decision_create --project-id 1 --type efficiency --title "Низкая конверсия"

Создаёт решение (draft). Advisory: ничего не применяет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_decision_engine_service import (
    AIDecisionEngineError,
    get_ai_decision_engine_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания решения."""
    parser = argparse.ArgumentParser(description="Создание решения AI Decision Engine")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--type", dest="decision_type", default="growth")
    parser.add_argument("--title", required=True)
    parser.add_argument("--problem", default=None)
    parser.add_argument("--objective", default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания решения."""
    args = build_parser().parse_args()
    service = get_ai_decision_engine_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            decision = service.create_decision(
                db,
                args.project_id,
                decision_type=args.decision_type,
                title=args.title,
                problem_statement=args.problem,
                objective=args.objective,
            )
        except AIDecisionEngineError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"decision_id:    {decision['id']} ({decision['decision_type']}, {decision['status']})")
    print(f"title:          {decision['title']}")


if __name__ == "__main__":
    main()
