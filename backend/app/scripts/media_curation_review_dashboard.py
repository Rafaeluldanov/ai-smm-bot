"""CLI сводки доски ревью медиатеки (read-only, без записи).

Запуск:
  make media-curation-review-dashboard project_id=1
  python -m app.scripts.media_curation_review_dashboard --project-id 1

Секреты/пути к файлам не печатаются; файлы не удаляются; live/внешнего AI нет.
"""

import argparse

from app.api.deps import get_media_curation_review_service
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки ревью."""
    parser = argparse.ArgumentParser(description="Сводка доски ревью медиатеки")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI сводки ревью."""
    args = build_parser().parse_args()
    service = get_media_curation_review_service()
    factory = get_sessionmaker()
    with factory() as db:
        dash = service.build_review_dashboard(db, args.project_id)
    print(f"Ревью медиатеки: проект {dash['project_id']}")
    print(
        f"  proposed: {dash['proposed']} · assigned: {dash['assigned']} · "
        f"in_review: {dash['in_review']} · changes_requested: {dash['changes_requested']}"
    )
    print(
        f"  approved: {dash['approved']} · applied: {dash['applied']} · "
        f"rejected: {dash['rejected']} · overdue: {dash['overdue']}"
    )
    print(
        f"  активных задач ревью: {dash['active_review_tasks']} · "
        f"по приоритету: {dash['by_priority']}"
    )
    print(
        f"  require_approval: {dash['require_approval']} · "
        f"auto_apply_after_approval: {dash['auto_apply_after_approval']} · "
        f"notify: {dash['notify_enabled']} · external_ai: {dash['external_ai_enabled']}"
    )
    print("  Изменения — только после approved; файлы не удаляются; внешнего AI нет.")


if __name__ == "__main__":
    main()
