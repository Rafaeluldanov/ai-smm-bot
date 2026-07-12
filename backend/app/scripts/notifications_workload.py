"""CLI нагрузки ревьюеров проекта (read-only, без записи).

Запуск:
  make notifications-workload project_id=1
  python -m app.scripts.notifications_workload --project-id 1

Секреты/пути к файлам не печатаются; внешней доставки нет.
"""

import argparse

from app.api.deps import get_notification_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов workload."""
    parser = argparse.ArgumentParser(description="Нагрузка ревьюеров проекта")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI workload."""
    args = build_parser().parse_args()
    service = get_notification_service()
    factory = get_sessionmaker()
    with factory() as db:
        wl = service.build_review_workload(db, args.project_id)
    print(f"Нагрузка ревьюеров · проект {wl['project_id']} · SLA {wl.get('sla_hours')} ч")
    print(f"  без назначения (активные): {wl.get('unassigned_active', 0)}")
    for r in wl["reviewers"]:
        print(
            f"  ревьюер #{r['reviewer_user_id']}: задач {r['assigned_count']} · overdue "
            f"{r['overdue_count']} · high/urgent {r['high_priority_count']} · ср. возраст "
            f"{r['avg_age_hours']} ч · SLA {r['sla_status']}"
        )
    if not wl["reviewers"]:
        print("  Назначенных ревьюеров нет.")


if __name__ == "__main__":
    main()
