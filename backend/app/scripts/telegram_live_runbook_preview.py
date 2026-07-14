"""CLI предпросмотра тестового поста Telegram runbook — v0.6.3.

Запуск:
  make telegram-runbook-preview project_id=1 [post_id=1]
  python -m app.scripts.telegram_live_runbook_preview --project-id 1 --post-id 1

Собирает предпросмотр (текст/медиа/хэштеги) БЕЗ отправки. Секретов/сырого токена не печатает
(media_url маскирован).
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_runbook_service import (
    TelegramLiveRunbookError,
    get_telegram_live_runbook_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра runbook."""
    parser = argparse.ArgumentParser(description="Предпросмотр тестового поста Telegram runbook")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--post-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра runbook."""
    args = build_parser().parse_args()
    service = get_telegram_live_runbook_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.prepare_test_post(db, args.project_id, post_id=args.post_id)
        except TelegramLiveRunbookError as exc:
            print(f"Ошибка: {exc}")
            return
    payload = result["attempt"]["payload_preview"]
    print(f"post_id:         {result['post_id']}")
    print(f"writes:          {result['writes']}")
    print(f"live_calls:      {result['live_calls']}")
    print(f"text_length:     {payload.get('text_length')}")
    print(f"hashtags:        {' '.join(payload.get('hashtags', [])) or '—'}")
    print(f"media_count:     {payload.get('media_count')}")
    print(f"media_url:       {payload.get('media_url_masked') or '—'}")
    print(result["note"])


if __name__ == "__main__":
    main()
