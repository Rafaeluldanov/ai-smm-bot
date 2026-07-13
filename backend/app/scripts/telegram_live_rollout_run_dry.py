"""CLI тестового прогона Telegram live rollout (без отправки) — v0.6.0.

Запуск:
  make telegram-live-rollout-run-dry project_id=1 post_id=1
  python -m app.scripts.telegram_live_rollout_run_dry --project-id 1 --post-id 1

Проверяет гейты и пишет запись попытки БЕЗ реальной отправки и без списания. Секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_rollout_service import get_telegram_live_rollout_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов тестового прогона rollout."""
    parser = argparse.ArgumentParser(
        description="Тестовый прогон Telegram live rollout (без отправки)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--post-id", type=int, default=None)
    parser.add_argument("--publication-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI тестового прогона rollout."""
    args = build_parser().parse_args()
    service = get_telegram_live_rollout_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_once_dry(
            db, args.project_id, post_id=args.post_id, publication_id=args.publication_id
        )
    print(f"attempt_id:      {result['id']}")
    print(f"status:          {result['status']}")
    print(f"mode:            {result['mode']}")
    print(f"live_calls:      {result['live_calls']}")
    print(f"units_charged:   {result['units_charged']}")
    for blocker in result["blockers"]:
        print(f"  blocker: {blocker.get('type')}")
    print(result["note"])


if __name__ == "__main__":
    main()
