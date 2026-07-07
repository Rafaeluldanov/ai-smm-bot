"""CLI: SEO-контент-план проекта на N дней (без сети и AI).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.generate_seo_content_plan \
      --project-slug teeon --days 30

Выводит по дням: дата/день, рубрику, тему, SEO-запрос, продукт/технологию,
ссылку на сайт, рекомендуемый медиа-тег и CTA. По умолчанию оффлайн; флаг
``--with-media`` дополнительно подбирает собственное approved-медиа из БД (и
показывает preferred_media_path улучшенной копии, если она есть).
"""

import argparse
from datetime import date, datetime

from app.schemas.seo import SeoContentPlanItem
from app.services.seo_content_plan_service import SeoContentPlanService
from app.services.seo_content_sources import UnknownSeoProjectError


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _enrich_with_media(project_slug: str, items: list[SeoContentPlanItem]) -> dict[int, str]:
    """Подобрать собственное медиа под элементы плана (опционально, требует БД)."""
    from app.db.session import get_sessionmaker
    from app.services.seo_media_selection_service import SeoMediaSelectionService
    from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

    service = SeoMediaSelectionService()
    notes: dict[int, str] = {}
    factory = get_sessionmaker()
    with factory() as db:
        for item in items:
            products = [item.product] if item.product else []
            technologies = [item.technology] if item.technology else []
            try:
                best = service.select_best(db, project_slug, products, technologies)
            except ProjectNotFoundError:
                return {}
            if best is not None:
                path = best.preferred_media_path or "(оригинал)"
                notes[item.day_number] = (
                    f"медиа id={best.media_asset_id} [{best.media_source}] {path}"
                )
    return notes


def main() -> None:
    """Точка входа CLI SEO-контент-плана."""
    parser = argparse.ArgumentParser(description="SEO-контент-план проекта")
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument(
        "--start-date", default=None, help="Дата начала YYYY-MM-DD (по умолчанию сегодня)"
    )
    parser.add_argument("--with-media", action="store_true", help="Подобрать медиа из БД")
    args = parser.parse_args()

    try:
        plan = SeoContentPlanService().build_plan(
            args.project_slug, days=args.days, start_date=_parse_date(args.start_date)
        )
    except UnknownSeoProjectError as exc:
        print(f"Ошибка: {exc}")
        return

    media_notes: dict[int, str] = {}
    if args.with_media:
        try:
            media_notes = _enrich_with_media(args.project_slug, plan.items)
        except Exception as exc:  # noqa: BLE001 — БД может быть недоступна
            print(f"(медиа не подобрано: {exc})")

    print(f"SEO-контент-план: {plan.brand_name} ({plan.project_slug})")
    print(f"Дней: {plan.days}, старт: {plan.start_date}, сайт: {plan.site_url}")
    print(f"Распределение рубрик: {plan.rubric_distribution}\n")
    for item in plan.items:
        subject = item.technology or item.product or "—"
        print(f"День {item.day_number:>2} {item.date} {item.weekday} [{item.rubric}] {item.topic}")
        print(f"        SEO: {item.seo_query} (f={item.seo_frequency}) | {subject}")
        print(f"        Ссылка: {item.site_url} ({item.site_page_title})")
        print(f"        Медиа-тег: {item.media_tag} | CTA: {item.cta}")
        if item.day_number in media_notes:
            print(f"        Подбор: {media_notes[item.day_number]}")

    if plan.warnings:
        print("\nПредупреждения:")
        for warning in plan.warnings:
            print(f"  ! {warning}")


if __name__ == "__main__":
    main()
