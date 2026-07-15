"""CLI создания бизнес-цели AI Business Planner — v0.7.7.

Запуск:
  make goal-create project_id=1 type=revenue title="Выручка x5" target=5000000 current=1000000
  python -m app.scripts.goal_create --project-id 1 --type revenue --title "..." --target 5000000

Создаёт бизнес-цель (status=active). Advisory: план не строит, бизнес/CRM/бюджет не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_business_planner_service import (
    AIBusinessPlannerError,
    get_ai_business_planner_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов создания цели."""
    parser = argparse.ArgumentParser(description="Создание бизнес-цели AI Business Planner")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--type", dest="goal_type", default="revenue")
    parser.add_argument("--title", required=True)
    parser.add_argument("--target", type=float, default=0.0)
    parser.add_argument("--current", type=float, default=0.0)
    parser.add_argument("--description", default=None)
    return parser


def main() -> None:
    """Точка входа CLI создания цели."""
    args = build_parser().parse_args()
    service = get_ai_business_planner_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            goal = service.create_business_goal(
                db,
                args.project_id,
                goal_type=args.goal_type,
                title=args.title,
                description=args.description,
                target_value=args.target,
                current_value=args.current,
            )
        except AIBusinessPlannerError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"goal_id:        {goal['id']} ({goal['goal_type']}, {goal['status']})")
    print(f"title:          {goal['title']}")
    print(f"current→target: {goal['current_value']} → {goal['target_value']} (gap {goal['gap']})")


if __name__ == "__main__":
    main()
