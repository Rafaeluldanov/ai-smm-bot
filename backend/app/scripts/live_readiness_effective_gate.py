"""CLI эффективного live-гейта (project × platform) — v0.5.9.

Запуск:
  make live-readiness-effective-gate project_id=1 platform=telegram
  python -m app.scripts.live_readiness_effective_gate --project-id 1 --platform telegram

Показывает, может ли проект реально публиковать на площадке и что мешает. Глобальные live-флаги
обязательны и не обходятся. Ничего не публикует, секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_readiness_service import get_live_readiness_service


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов эффективного гейта."""
    parser = argparse.ArgumentParser(description="Эффективный live-гейт (project × platform)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", type=str, required=True)
    return parser


def main() -> None:
    """Точка входа CLI эффективного live-гейта."""
    args = build_parser().parse_args()
    service = get_live_readiness_service()
    factory = get_sessionmaker()
    with factory() as db:
        gate = service.build_effective_live_gate(db, args.project_id, args.platform)
    print(f"platform:              {gate['platform_key']}")
    print(f"global_live_enabled:   {gate['global_live_enabled']}")
    print(f"project_live_enabled:  {gate['project_live_enabled']}")
    print(f"platform_live_enabled: {gate['platform_live_enabled']}")
    print(f"full_auto_live_enabled:{gate['full_auto_live_enabled']}")
    print(f"readiness_ready:       {gate['readiness_ready']}")
    print(f"can_publish_live:      {gate['can_publish_live']}")
    print(f"blocked_reasons:       {', '.join(gate['blocked_reasons']) or '—'}")


if __name__ == "__main__":
    main()
