"""CLI проверки готовности проекта к реальной автопубликации — v0.5.9.

Запуск:
  make live-readiness-check project_id=1 dry_run=true
  python -m app.scripts.live_readiness_check --project-id 1 [--dry-run true]

Печатает статус, готовность, блокеры и чек-лист. По умолчанию dry-run (без записи). Ничего не
публикует, глобальные live-флаги не трогает, внешних вызовов нет, секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_readiness_service import get_live_readiness_service


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов проверки готовности проекта."""
    parser = argparse.ArgumentParser(description="Проверка готовности проекта к автопубликации")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI проверки готовности проекта."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_live_readiness_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_project_readiness_check(db, args.project_id, dry_run=dry_run)
    print(f"dry_run:         {dry_run}")
    print(f"status:          {result['status']}")
    print(f"readiness_score: {result['readiness_score']}")
    print(f"can_enable_live: {result['can_enable_live']}")
    print(f"live_mode:       {result['live_mode']}")
    for item, meta in result["checklist"].items():
        print(f"  [{'x' if meta.get('done') else ' '}] {meta.get('label', item)}")
    for blocker in result["blockers"]:
        print(f"  blocker [{blocker['severity']}] {blocker['type']}: {blocker['message']}")
    print("Ничего не опубликовано; глобальные условия публикации не меняются.")


if __name__ == "__main__":
    main()
