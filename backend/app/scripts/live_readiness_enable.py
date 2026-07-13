"""CLI включения per-project live (готовность к автопубликации) — v0.5.9.

Запуск:
  make live-readiness-enable project_id=1 confirmation=ENABLE_LIVE_AUTOPILOT dry_run=true
  python -m app.scripts.live_readiness_enable --project-id 1 \
      --confirmation ENABLE_LIVE_AUTOPILOT --dry-run true

По умолчанию dry-run: показывает, разрешит ли система включение, БЕЗ записи. С --dry-run false и
верным подтверждением включает per-project live. НИКОГДА не включает глобальные live-флаги и не
публикует.
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.live_readiness_service import LiveReadinessError, get_live_readiness_service


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов включения live проекта."""
    parser = argparse.ArgumentParser(description="Включить per-project live (готовность)")
    parser.add_argument("--project-id", type=int, required=True)
    parser.add_argument("--confirmation", type=str, default="")
    parser.add_argument("--dry-run", dest="dry_run", type=str, default="true")
    return parser


def main() -> None:
    """Точка входа CLI включения live проекта."""
    args = build_parser().parse_args()
    dry_run = _as_bool(args.dry_run)
    service = get_live_readiness_service()
    factory = get_sessionmaker()
    with factory() as db:
        if dry_run:
            check = service.run_project_readiness_check(db, args.project_id, dry_run=True)
            print("dry_run:         True")
            print(f"status:          {check['status']}")
            print(f"can_enable_live: {check['can_enable_live']}")
            print("Ничего не изменено (dry-run). Глобальные live-флаги не трогаются.")
            return
        try:
            result = service.enable_project_live(db, args.project_id, args.confirmation)
        except LiveReadinessError as exc:
            print(f"blocked: {exc}")
            return
        print(f"project_live_enabled: {result['project_live_enabled']}")
        print(f"global_flags_changed: {result['global_flags_changed']}")
        print(result["note"])


if __name__ == "__main__":
    main()
