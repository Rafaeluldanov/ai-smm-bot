"""CLI: контент-план категории продвижения на N дней (требует БД).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_crm_category_plan \
      --category-id 1 --days 30

Каждый день содержит тему, SEO-запрос, продукт/технологию и ссылку на сайт.
Публикаций не выполняет.
"""

import argparse

from app.services.crm_bot_smm_application_service import (
    CrmBotSmmApplicationService,
    CrmCategoryNotFoundError,
    CrmConfigNotFoundError,
)


def main() -> None:
    """Точка входа CLI контент-плана категории."""
    parser = argparse.ArgumentParser(description="Контент-план категории «БОТ СММ»")
    parser.add_argument("--category-id", type=int, required=True)
    parser.add_argument("--days", type=int, default=30)
    args = parser.parse_args()

    from app.db.session import get_sessionmaker

    service = CrmBotSmmApplicationService()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            plan = service.build_content_plan_from_category(db, args.category_id, days=args.days)
        except (CrmCategoryNotFoundError, CrmConfigNotFoundError) as exc:
            print(f"Ошибка: {exc}")
            return

    print(f"Контент-план: {plan.brand_name} ({plan.project_slug})")
    print(f"Дней: {plan.days}, старт: {plan.start_date}, сайт: {plan.site_url}")
    print(f"Распределение рубрик: {plan.rubric_distribution}\n")
    for item in plan.items:
        subject = item.technology or item.product or "—"
        print(f"День {item.day_number:>2} {item.date} {item.weekday} [{item.rubric}] {item.topic}")
        print(f"        SEO: {item.seo_query} | {subject}")
        print(f"        Ссылка: {item.site_url} ({item.site_page_title})")
        print(f"        Медиа-тег: {item.media_tag} | CTA: {item.cta}")
    if plan.warnings:
        print("\nПредупреждения:")
        for warning in plan.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
