"""CLI: создать URL доставки media-proxy для актива с трансформацией — v0.6.2.

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.media_proxy_generate \\
        --project-id 1 --media-asset-id 123 --transform width_1080 --show-url true

По умолчанию печатается ТОЛЬКО маскированный URL (безопасно). Реальный URL — лишь при
``--show-url true``. Raw-токен нигде не логируется. С ``--platform`` создаётся набор ссылок.
"""

from __future__ import annotations

import argparse
import sys

from app.db.session import get_sessionmaker
from app.services.media_proxy_service import MediaProxyError, MediaProxyService


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Создать URL доставки media-proxy")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--media-asset-id", type=int, required=True)
    parser.add_argument("--transform", default="width_1080")
    parser.add_argument("--platform", default=None, help="instagram|vk|telegram (набор ссылок)")
    parser.add_argument("--ttl-seconds", type=int, default=None)
    parser.add_argument("--show-url", default="false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    service = MediaProxyService()
    with get_sessionmaker()() as db:
        try:
            if args.platform:
                result = service.build_social_media_url(
                    db, args.project_id, args.media_asset_id, args.platform, args.ttl_seconds
                )
            else:
                result = service.create_media_url(
                    db,
                    args.project_id,
                    args.media_asset_id,
                    transform=args.transform,
                    ttl_seconds=args.ttl_seconds,
                )
        except MediaProxyError as exc:
            print(f"Ошибка: {exc}")
            return 2
    print(f"link id:      {result.id}")
    print(f"transform:    {result.transform}")
    print(f"token_type:   {result.token_type}")
    print(f"masked URL:   {result.url_masked}")
    print(f"expires_at:   {result.expires_at}")
    for warning in result.warnings:
        print(f"warning: {warning}")
    if _bool(args.show_url):
        print(f"URL: {result.url}")
    else:
        print("(реальный URL скрыт; для показа добавьте --show-url true)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
