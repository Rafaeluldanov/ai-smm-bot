"""CLI дашборда Telegram live rollout — v0.6.0.

Запуск:
  make telegram-live-rollout-dashboard project_id=1
  python -m app.scripts.telegram_live_rollout_dashboard --project-id 1

Показывает статус Telegram live, условия публикации и последнюю попытку. Ничего не публикует,
глобальные флаги не трогает, секретов/токенов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_rollout_service import get_telegram_live_rollout_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов дашборда rollout."""
    parser = argparse.ArgumentParser(description="Дашборд Telegram live rollout")
    parser.add_argument("--project-id", type=int, required=True)
    return parser


def main() -> None:
    """Точка входа CLI дашборда rollout."""
    args = build_parser().parse_args()
    service = get_telegram_live_rollout_service()
    factory = get_sessionmaker()
    with factory() as db:
        d = service.build_dashboard(db, args.project_id)
    print(f"status:              {d['status']}")
    print(f"global_live:         {d['global_live_flag_status']}")
    print(f"project_live:        {d['project_live_status']}")
    print(f"platform_live:       {d['platform_live_status']}")
    print(f"full_auto_live:      {d['full_auto_live_status']}")
    print(f"rollout_allow_real:  {d['rollout_allow_real_send']}")
    print(f"can_send_real:       {d['readiness']['can_send_real']}")
    last = d["last_attempt"]
    print(f"last_attempt:        {last['status'] if last else '—'}")
    for blocker in d["blockers"]:
        print(f"  blocker {blocker['type']}: {blocker['message']}")
    print("Ничего не опубликовано; глобальные условия публикации не меняются.")


if __name__ == "__main__":
    main()
