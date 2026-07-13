"""CLI предпросмотра Telegram live rollout — v0.6.0.

Запуск:
  make telegram-live-rollout-preview project_id=1 post_id=1
  python -m app.scripts.telegram_live_rollout_preview --project-id 1 --post-id 1

Безопасный предпросмотр Telegram-публикации. Без записи, без сети, без списания, без секретов.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.telegram_live_rollout_service import get_telegram_live_rollout_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов предпросмотра rollout."""
    parser = argparse.ArgumentParser(description="Предпросмотр Telegram live rollout")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--post-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI предпросмотра rollout."""
    args = build_parser().parse_args()
    service = get_telegram_live_rollout_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.preview_post(db, args.project_id, args.post_id)
    p = result["payload_preview"]
    st = result["effective_status"]
    print(f"post_id:         {result['post_id']}")
    print(f"can_attempt_live:{st['can_attempt_live']}")
    print(f"can_send_real:   {st['can_send_real']}")
    if p.get("available"):
        print(f"text_length:     {p['text_length']}")
        print(f"media_count:     {p['media_count']}")
        print(f"would_send:      {p['would_send']}")
    print(f"writes:          {result['writes']}")
    print(f"live_calls:      {result['live_calls']}")
    print(result["note"])


if __name__ == "__main__":
    main()
