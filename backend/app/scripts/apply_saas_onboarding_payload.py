"""CLI: preview/apply SaaS-онбординг пейлоада под аккаунт.

По умолчанию dry-run (ничего не пишет в БД). Публикации не выполняются. Реальный
apply (``--dry-run false``) создаёт проект/конфиг под аккаунтом и провижинит
биллинг; требует доступной БД и существующего account_id.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.apply_saas_onboarding_payload \\
      --account-id 1 --payload-path backend/examples/saas_onboarding_teeon.json --dry-run true
"""

import argparse
import json
from pathlib import Path

from app.api.deps import get_saas_onboarding_service
from app.db.session import get_sessionmaker
from app.schemas.saas_onboarding import SaasOnboardingPayload, SaasOnboardingResult
from app.services.crm_bot_smm_form_service import CrmOnboardingValidationError
from app.services.saas_onboarding_service import SaasOnboardingError


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов SaaS-онбординга."""
    parser = argparse.ArgumentParser(description="Preview/apply SaaS-онбординга под аккаунт")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--payload-path", required=True)
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--allow-live", default="false")
    return parser


def _print_result(result: SaasOnboardingResult) -> None:
    mode = "dry-run (без записи)" if result.dry_run else "apply (записано)"
    print(f"SaaS онбординг: {mode}")
    print(f"  account_id={result.account_id} project_id={result.project_id}")
    print(f"  проект: {result.crm.project.slug} / {result.crm.project.display_name}")
    print(f"  платформы/ресурсы: {len(result.crm.resources)} (секрет не показывается)")
    print(f"  ключей: {result.crm.keywords_count}")
    print(f"  медиа-источников: {result.crm.content_sources_count}")
    print(f"  категорий: {len(result.crm.categories)}; планов: {len(result.crm.plans)}")
    print(f"  баланс биллинга: {result.billing_balance_units} units")
    for warning in result.warnings:
        print(f"  ! {warning}")


def main() -> None:
    """Точка входа CLI SaaS-онбординга."""
    args = build_parser().parse_args()
    dry_run = _parse_bool(args.dry_run)
    allow_live = _parse_bool(args.allow_live)
    payload = SaasOnboardingPayload.model_validate(
        json.loads(Path(args.payload_path).read_text(encoding="utf-8"))
    )
    service = get_saas_onboarding_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            if dry_run:
                result = service.preview(db, args.account_id, payload, allow_live)
            else:
                result = service.apply(db, args.account_id, payload, allow_live)
        except (SaasOnboardingError, CrmOnboardingValidationError) as exc:
            print(f"Ошибка: {exc}")
            return
        _print_result(result)


if __name__ == "__main__":
    main()
