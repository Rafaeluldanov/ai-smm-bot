"""CLI построения исполнительного плана Autonomous Business OS — v0.7.0.

Запуск:
  make business-os-plan project_id=1
  python -m app.scripts.business_os_plan --project-id 1 [--objective-id 3]

Строит исполнительный план: резюме + приоритеты + бизнес-действия. Advisory: ничего не запускает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.ai_executive_service import AIExecutiveError, get_ai_executive_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов построения плана."""
    parser = argparse.ArgumentParser(description="Исполнительный план Autonomous Business OS")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--objective-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI построения исполнительного плана."""
    args = build_parser().parse_args()
    service = get_ai_executive_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            out = service.create_executive_plan(db, args.project_id, objective_id=args.objective_id)
        except AIExecutiveError as exc:
            print(f"Ошибка: {exc}")
            return
    plan = out["plan"]
    print(f"plan_id:        {plan['id']}")
    print(f"summary:        {plan['executive_summary']}")
    print(f"confidence:     {plan['confidence_score']} / 100")
    print(f"priorities:     {', '.join(str(p) for p in plan['priority_actions']) or '—'}")
    print(f"actions:        {len(out['actions'])} создано")
    for a in out["actions"]:
        print(f"  [{a['action_type']}] {a['title']} (приоритет {a['priority']})")


if __name__ == "__main__":
    main()
