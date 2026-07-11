"""CLI: создать временную публичную ссылку на медиа (media-proxy).

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.create_public_media_link \\
        --project-id 1 --media-asset-id 123 --purpose instagram --ttl-seconds 86400

По умолчанию печатается ТОЛЬКО маскированный URL (безопасно). Реальный URL печатается
лишь при ``--show-url true`` (для локальной проверки). Raw-токен нигде не логируется.
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import get_sessionmaker
from app.services.media_proxy_service import MediaProxyError, MediaProxyService


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Создать публичную media-ссылку (media-proxy)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--media-asset-id", type=int, required=True)
    parser.add_argument("--purpose", default="instagram")
    parser.add_argument("--ttl-seconds", type=int, default=None)
    parser.add_argument(
        "--show-url", default="false", help="true → напечатать реальный URL (небезопасно)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    service = MediaProxyService()
    with get_sessionmaker()() as db:
        try:
            result = service.create_public_link(
                db,
                project_id=args.project_id,
                media_asset_id=args.media_asset_id,
                purpose=args.purpose,
                ttl_seconds=args.ttl_seconds,
            )
        except MediaProxyError as exc:
            print(f"Ошибка: {exc}")
            return 2
    print(f"link id: {result.id}")
    print(f"masked URL: {result.url_masked}")
    print(f"expires_at: {result.expires_at}")
    print(f"content_type: {result.content_type}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if _bool(args.show_url):
        print(f"URL: {result.url}")
    else:
        print("(реальный URL скрыт; для показа добавьте --show-url true)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
