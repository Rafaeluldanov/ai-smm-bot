"""CLI ручного production-теста Telegram runbook — v0.6.3.

Запуск:
  make telegram-runbook-publish-test project_id=1 confirmation=ENABLE_TELEGRAM_LIVE dry_run=true
  python -m app.scripts.telegram_live_runbook_publish_test --project-id 1 \
      --confirmation ENABLE_TELEGRAM_LIVE --dry-run true

По умолчанию dry-run: показывает готовность к реальной отправке БЕЗ отправки. Реальная отправка
(--dry-run false) сработает ТОЛЬКО если включены глобальный TELEGRAM_LIVE_PUBLISHING_ENABLED +
per-project/per-platform live + full_auto + readiness + allow_real_send + подтверждение. Секретов
не печатает; глобальные флаги не меняет.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_runbook_service import (
    TelegramLiveRunbookError,
    get_telegram_live_runbook_service,
)


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов production-теста runbook."""
    parser = argparse.ArgumentParser(description="Ручной production-тест Telegram runbook")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--post-id", type=int, default=None)
    parser.add_argument("--confirmation", type=str, default="")
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI production-теста runbook."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_telegram_live_runbook_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if dry_run:
                result = service.confirm_live_publish(
                    db, args.project_id, args.confirmation, post_id=args.post_id
                )
                print("dry_run:         True (реальной отправки нет)")
                print(f"allowed:         {result['allowed']}")
                print(f"can_send_real:   {result['can_send_real']}")
                for blocker in result["blockers"]:
                    print(f"  blocker {blocker['type']}: {blocker['message']}")
                print("Уберите --dry-run false для реальной отправки (если всё включено).")
                return
            result = service.publish_test_post(
                db,
                args.project_id,
                post_id=args.post_id,
                confirmation_text=args.confirmation,
            )
        except TelegramLiveRunbookError as exc:
            print(f"Ошибка: {exc}")
            return
    attempt = result["attempt"]
    print(f"status:          {attempt['status']}")
    print(f"published:       {result['published']}")
    print(f"live_calls:      {result['live_calls']}")
    if attempt.get("external_url"):
        print(f"external_url:    {attempt['external_url']}")
    print(result.get("note", ""))


if __name__ == "__main__":
    main()
