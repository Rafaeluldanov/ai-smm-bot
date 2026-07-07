"""CLI: применить онбординг-пейлоад формы «БОТ СММ».

По умолчанию dry-run (ничего не пишет в БД). Публикации не выполняются ни в
каком режиме. Реальное применение (``--dry-run false``) создаёт проект,
конфигурацию, ресурсы, ключи, категории и планы и требует доступной БД.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.apply_crm_onboarding_payload \
      --payload-path backend/examples/crm_bot_smm_onboarding_teeon.json --dry-run true
"""

import argparse
import json
from pathlib import Path

from app.schemas.crm_bot_smm import CrmPreviewResult
from app.services.crm_bot_smm_form_service import (
    CrmBotSmmFormService,
    CrmOnboardingValidationError,
)


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _print_preview(result: CrmPreviewResult) -> None:
    mode = "dry-run (без записи)" if result.dry_run else "apply (записано)"
    print(f"Онбординг: {mode}")
    print(
        f"Проект: {result.project.slug} / {result.project.display_name} "
        f"(существует={result.project.exists}, сайт={result.project.website_url or '—'})"
    )
    if result.config_id is not None:
        print(f"config_id: {result.config_id}")
    print(f"Ресурсы ({len(result.resources)}):")
    for res in result.resources:
        print(
            f"  • {res.title} [{res.resource_type}] "
            f"секрет={'есть' if res.api_key_present else 'нет'} live={res.live_enabled}"
        )
    print(f"Ключей: {result.keywords_count}; источников: {result.content_sources_count}")
    print(f"Категории ({len(result.categories)}):")
    for cat in result.categories:
        print(f"  • {cat.title}: ключей={cat.keyword_count}, сайт={cat.default_site_url or '—'}")
    print(f"Планы ({len(result.plans)}):")
    for plan in result.plans:
        print(
            f"  • {plan.category_title or '—'}: режим={plan.mode}, "
            f"дни={plan.weekdays}, платформы={plan.platforms}"
        )
    if result.warnings:
        print("Предупреждения:")
        for warning in result.warnings:
            print(f"  ~ {warning}")
    if result.next_commands:
        print("Дальше:")
        for command in result.next_commands:
            print(f"  → {command}")


def main() -> None:
    """Точка входа CLI применения онбординга."""
    parser = argparse.ArgumentParser(description="Применение онбординга «БОТ СММ»")
    parser.add_argument("--payload-path", required=True, help="Путь к JSON-файлу пейлоада")
    parser.add_argument("--dry-run", default="true", help="true (по умолчанию) / false")
    args = parser.parse_args()

    dry_run = _parse_bool(args.dry_run)
    payload = json.loads(Path(args.payload_path).read_text(encoding="utf-8"))
    service = CrmBotSmmFormService()

    from app.db.session import get_sessionmaker

    factory = get_sessionmaker()
    with factory() as db:
        try:
            result = service.apply_onboarding_payload(db, payload, dry_run=dry_run)
        except CrmOnboardingValidationError as exc:
            print("Пейлоад не прошёл валидацию:")
            for error in exc.errors:
                print(f"  ! {error}")
            return
        _print_preview(result)


if __name__ == "__main__":
    main()
