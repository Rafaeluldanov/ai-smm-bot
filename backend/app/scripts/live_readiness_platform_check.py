"""CLI проверки готовности площадки к реальной автопубликации — v0.5.9.

Запуск:
  make live-readiness-platform-check project_id=1 platform=telegram dry_run=true
  python -m app.scripts.live_readiness_platform_check --project-id 1 \
      --platform telegram --dry-run true

Печатает статус площадки, недостающие поля и глобальный статус условий публикации. По умолчанию
dry-run. Ничего не публикует, внешних probe-вызовов нет, секретов не печатает.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_readiness_service import get_live_readiness_service


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов проверки готовности площадки."""
    parser = argparse.ArgumentParser(description="Проверка готовности площадки к автопубликации")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--platform", type=str, required=True)
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI проверки готовности площадки."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_live_readiness_service()
    factory = get_sessionmaker()
    with factory() as db:
        result = service.run_platform_readiness_check(
            db, args.project_id, args.platform, dry_run=dry_run
        )
    print(f"platform:         {result['platform_key']}")
    print(f"status:           {result['status']}")
    print(f"readiness_score:  {result['readiness_score']}")
    print(f"global_live:      {result.get('global_live_enabled')}")
    print(f"platform_live:    {result.get('platform_live_enabled')}")
    print(f"credentials:      {result.get('credentials_present')}")
    print(f"missing_fields:   {', '.join(result.get('missing_fields', [])) or '—'}")
    for blocker in result["blockers"]:
        print(f"  blocker [{blocker['severity']}] {blocker['type']}: {blocker['message']}")
    print("Ничего не опубликовано; токены не печатаются; глобальные флаги не меняются.")


if __name__ == "__main__":
    main()
