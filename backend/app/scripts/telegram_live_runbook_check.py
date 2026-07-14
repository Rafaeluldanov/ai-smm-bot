"""CLI проверки готовности Telegram runbook — v0.6.3.

Запуск:
  make telegram-runbook-check project_id=1
  python -m app.scripts.telegram_live_runbook_check --project-id 1

Показывает чек-лист готовности первого Telegram-канала. Ничего не публикует, глобальные флаги
не трогает, секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_runbook_service import get_telegram_live_runbook_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов проверки runbook."""
    parser = argparse.ArgumentParser(description="Проверка готовности Telegram runbook")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI проверки runbook."""
    args = build_parser().parse_args()
    service = get_telegram_live_runbook_service()
    factory = get_sessionmaker()
    with factory() as db:
        d = service.build_checklist(db, args.project_id, dry_run=False)
    print(f"status:          {d['status']}")
    print(f"ready:           {d['ready']}")
    print(f"channel:         {d['channel_name'] or d['channel_id'] or '—'}")
    print(f"can_send_real:   {d['can_send_real']}")
    for key, item in d["checklist"].items():
        print(f"  [{'x' if item['done'] else ' '}] {key}: {item['label']}")
    for blocker in d["blockers"]:
        print(f"  blocker {blocker['type']}: {blocker['message']}")
    print(d["note"])


if __name__ == "__main__":
    main()
