"""CLI однократной live-публикации Telegram (под всеми гейтами) — v0.6.0.

Запуск:
  make telegram-live-rollout-publish-once project_id=1 post_id=1 \
      confirmation=ENABLE_TELEGRAM_LIVE dry_run=true
  python -m app.scripts.telegram_live_rollout_publish_once --project-id 1 --post-id 1 \
      --confirmation ENABLE_TELEGRAM_LIVE --dry-run true

По умолчанию dry-run: показывает, разрешена ли реальная отправка, БЕЗ отправки. Реальная отправка
(--dry-run false) сработает ТОЛЬКО если включены глобальный TELEGRAM_LIVE_PUBLISHING_ENABLED +
per-project/per-platform live + full_auto + rollout allow_real_send + подтверждение. Секретов не
печатает; глобальные флаги не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_rollout_service import get_telegram_live_rollout_service


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов live-публикации rollout."""
    parser = argparse.ArgumentParser(
        description="Однократная live-публикация Telegram (под гейтами)"
    )
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--post-id", type=int, default=None)
    parser.add_argument("--publication-id", type=int, default=None)
    parser.add_argument("--confirmation", type=str, default="")
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI live-публикации rollout."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_telegram_live_rollout_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            # Dry-run: только проверка гейтов, без реальной попытки отправки.
            result = service.run_once_dry(
                db, args.project_id, post_id=args.post_id, publication_id=args.publication_id
            )
            print("dry_run:         True (реальной отправки нет)")
            print(f"status:          {result['status']}")
            print(f"live_calls:      {result['live_calls']}")
            print(f"units_charged:   {result['units_charged']}")
            print(
                "Уберите --dry-run false, чтобы попробовать реальную отправку (если всё включено)."
            )
            return
        result = service.publish_once_if_allowed(
            db,
            args.project_id,
            post_id=args.post_id,
            publication_id=args.publication_id,
            confirmation=args.confirmation,
        )
        print(f"status:          {result['status']}")
        print(f"live_attempted:  {result['live_attempted']}")
        print(f"live_calls:      {result.get('live_calls')}")
        if result.get("external_url"):
            print(f"external_url:    {result['external_url']}")
        for blocker in result.get("blockers", []):
            print(f"  blocker {blocker.get('type')}: {blocker.get('message', '')}")
        print(result.get("note", ""))


if __name__ == "__main__":
    main()
