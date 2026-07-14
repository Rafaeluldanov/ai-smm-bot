"""CLI: проверить готовность media-proxy (домен/HTTPS/лимиты/ресайз) — v0.6.2.

Пример:
    PYTHONPATH=backend .venv/bin/python -m app.scripts.media_proxy_check

Показывает статус доставки: включён ли proxy, публичный base URL, HTTPS-готовность, TTL,
ресайз, лимит запросов, отдача оригинала. Секретов не печатает; ничего не меняет.
"""

from __future__ import annotations

import argparse
import sys

from app.services.media_proxy_service import MediaProxyService


def build_arg_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Проверка готовности media-proxy")


def main(argv: list[str] | None = None) -> int:
    build_arg_parser().parse_args(argv)
    service = MediaProxyService()
    s = service.settings
    status = service.validate_public_base_url()
    print(f"enabled:          {status['enabled']}")
    print(f"base_url:         {status['base_url'] or '—'}")
    print(f"https_ready:      {status['https_ready']}")
    print(f"default_ttl:      {status['default_ttl_seconds']} c")
    print(f"resize_enabled:   {s.media_proxy_resize_enabled_effective}")
    print(f"allow_original:   {s.media_proxy_allow_original_effective}")
    print(f"max_requests:     {s.media_proxy_max_requests_safe}")
    print(f"cache_enabled:    {s.media_proxy_cache_enabled}")
    print(f"cache_seconds:    {s.media_proxy_cache_seconds_safe}")
    for err in status.get("errors", []):
        print(f"error:   {err}")
    for warning in status.get("warnings", []):
        print(f"warning: {warning}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
