"""CLI: подготовить посты по календарю на сегодня (needs_review; без публикаций).

Для проекта TEEON аккаунта Станислава создаёт черновики на ревью:
- Telegram: media-group посты по тегу «футболка» (фото с Яндекс Диска); в
  ``generation_notes`` — ``media_files`` / ``media_asset_ids`` / ``media_count``;
- VK: text-only пост(ы) БЕЗ картинок (``generation_notes.media_policy=text_only``),
  т. к. корректного VK user-token для загрузки фото пока нет.

Ничего не публикует и не отправляет в live. При ``--dry-run true`` (по умолчанию)
в БД ничего не пишется — только предпросмотр того, что будет создано.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.create_today_calendar_posts \\
      --account-id 1 --project-slug teeon --date today \\
      --telegram-media-posts 2 --vk-text-posts 1 --dry-run true
"""

import argparse
from dataclasses import replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.api.deps import get_media_grouping_service
from app.db.session import get_sessionmaker
from app.models.crm_bot_smm import CrmPromotionCategory, CrmPublishingPlan
from app.models.post import Post
from app.models.project import Project
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import post_repository, project_repository
from app.schemas.post import PostCreate
from app.services.media_grouping_service import MediaGroupCandidate, MediaGroupingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

MOSCOW = ZoneInfo("Europe/Moscow")
TELEGRAM_TAG = "футболка"
DEFAULT_CATEGORY_TITLE = "Футболки и майки"


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _resolve_date(value: str) -> date:
    """``today`` → сегодня (Europe/Moscow); иначе ISO-дата ``YYYY-MM-DD``."""
    if value.strip().lower() in {"today", ""}:
        return datetime.now(MOSCOW).date()
    return date.fromisoformat(value.strip())


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов календаря на сегодня."""
    parser = argparse.ArgumentParser(description="Подготовить посты по календарю на сегодня")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--date", default="today")
    parser.add_argument("--telegram-media-posts", type=int, default=2)
    parser.add_argument("--vk-text-posts", type=int, default=1)
    parser.add_argument("--dry-run", default="true")
    return parser


# --------------------------------------------------------------------------- #
# Вспомогательное: проект, план на сегодня, разбиение медиа                     #
# --------------------------------------------------------------------------- #


class CalendarError(Exception):
    """Ошибка подготовки календаря (проект не найден / чужой аккаунт)."""


def resolve_project(db: Session, account_id: int, project_slug: str) -> Project:
    """Найти проект по slug и проверить принадлежность аккаунту."""
    project = project_repository.get_project_by_slug(db, project_slug)
    if project is None:
        raise CalendarError(f"Проект '{project_slug}' не найден.")
    if project.account_id is not None and project.account_id != account_id:
        raise CalendarError(
            f"Проект '{project_slug}' принадлежит другому аккаунту (#{project.account_id})."
        )
    return project


def plans_for_today(
    db: Session, project: Project, today: date
) -> list[tuple[CrmPromotionCategory, CrmPublishingPlan]]:
    """Активные планы проекта на сегодня (по дню недели и диапазону дат)."""
    config = crm_repo.get_config_by_project_id(db, project.id)
    if config is None:
        return []
    weekday = today.weekday()
    iso = today.isoformat()
    pairs: list[tuple[CrmPromotionCategory, CrmPublishingPlan]] = []
    for category in crm_repo.list_categories_by_config(db, config.id):
        for plan in crm_repo.list_plans_by_category(db, category.id):
            if not plan.is_active:
                continue
            if plan.weekdays and weekday not in plan.weekdays:
                continue
            if plan.start_date and plan.start_date > iso:
                continue
            if plan.end_date and plan.end_date < iso:
                continue
            pairs.append((category, plan))
    return pairs


def _pick_category(
    db: Session,
    project: Project,
    platform: str,
    today_plans: list[tuple[CrmPromotionCategory, CrmPublishingPlan]],
) -> CrmPromotionCategory | None:
    """Категория из плана на сегодня для платформы; иначе дефолтная/первая."""
    config = crm_repo.get_config_by_project_id(db, project.id)
    if config is None:
        return None
    for category, plan in today_plans:
        if platform in (plan.platforms or []):
            return category
    default = crm_repo.get_category_by_key(db, config.id, DEFAULT_CATEGORY_TITLE)
    if default is not None:
        return default
    categories = crm_repo.list_categories_by_config(db, config.id)
    return categories[0] if categories else None


def split_ids(ids: list[int], parts: int) -> list[list[int]]:
    """Разбить id медиа на ≤``parts`` непустых чанков (как можно равномернее)."""
    if parts <= 0 or not ids:
        return []
    parts = min(parts, len(ids))
    base, extra = divmod(len(ids), parts)
    chunks: list[list[int]] = []
    start = 0
    for index in range(parts):
        size = base + (1 if index < extra else 0)
        chunks.append(ids[start : start + size])
        start += size
    return chunks


# --------------------------------------------------------------------------- #
# Telegram media-group посты                                                   #
# --------------------------------------------------------------------------- #


def prepare_telegram_posts(
    db: Session,
    service: MediaGroupingService,
    project_slug: str,
    count: int,
    dry_run: bool,
    plan_title: str,
    publish_times: list[str],
) -> tuple[list[Post], list[dict[str, Any]], list[str]]:
    """Подготовить media-group посты Telegram по тегу «футболка».

    Возвращает (созданные посты, превью-элементы, предупреждения). В dry-run
    посты не создаются — только превью черновиков.
    """
    warnings: list[str] = []
    if count <= 0:
        return [], [], warnings

    groups = service.group_project_media(
        db, project_slug, tag=TELEGRAM_TAG, max_groups=1, limit_media=max(6, count * 4)
    )
    if not groups:
        warnings.append(
            f"Telegram: медиа по тегу «{TELEGRAM_TAG}» не найдено — посты не подготовлены "
            "(нужна синхронизация медиа проекта)."
        )
        return [], [], warnings

    base = groups[0]
    chunks = split_ids(list(base.media_asset_ids), count)
    if len(chunks) < count:
        warnings.append(
            f"Telegram: доступно медиа на {len(chunks)} постов из запрошенных {count} "
            "(ограничено числом фото по тегу)."
        )

    posts: list[Post] = []
    previews: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        candidate: MediaGroupCandidate = replace(base, media_asset_ids=list(chunk))
        publish_time = publish_times[index] if index < len(publish_times) else None
        extra_notes = {
            "platform_target": "telegram",
            "media_policy": "media_group",
            "plan_title": plan_title,
            "publish_time": publish_time,
        }
        if dry_run:
            draft = service.build_post_draft_from_group(db, project_slug, candidate)
            previews.append(
                {
                    "platform": "telegram",
                    "title": draft.title,
                    "media_count": draft.generation_notes.get("media_count"),
                    "media_asset_ids": draft.generation_notes.get("media_asset_ids"),
                    "publish_time": publish_time,
                }
            )
        else:
            post = service.create_post_from_media_group(
                db, project_slug, candidate, status="needs_review"
            )
            post.generation_notes = {**(post.generation_notes or {}), **extra_notes}
            db.commit()
            db.refresh(post)
            posts.append(post)
    return posts, previews, warnings


# --------------------------------------------------------------------------- #
# VK text-only посты                                                          #
# --------------------------------------------------------------------------- #


def build_vk_text(project: Project, category: CrmPromotionCategory | None) -> str:
    """Собрать VK text-only текст (без картинок) из проекта и категории."""
    site = (
        (category.default_site_url if category else None)
        or project.website_url
        or "https://teeon.ru"
    )
    cta = (category.cta if category and category.cta else "").strip()
    headline = category.title if category else "Корпоративный мерч"
    lines = [
        f"{project.name}: {headline.lower()}.",
        "Производим и брендируем одежду под ключ — расчёт тиража и подбор технологии нанесения.",
    ]
    if cta:
        lines.append(cta)
    lines.append(f"Подробнее: {site}")
    return "\n".join(lines)


def prepare_vk_posts(
    db: Session,
    project: Project,
    category: CrmPromotionCategory | None,
    count: int,
    dry_run: bool,
    plan_title: str,
    publish_times: list[str],
) -> tuple[list[Post], list[dict[str, Any]]]:
    """Подготовить VK text-only посты (без media_group, без картинок)."""
    posts: list[Post] = []
    previews: list[dict[str, Any]] = []
    if count <= 0:
        return posts, previews

    text = build_vk_text(project, category)
    title = f"{category.title if category else 'TEEON'} — VK (text-only)"
    for index in range(count):
        publish_time = publish_times[index] if index < len(publish_times) else None
        notes: dict[str, Any] = {
            "platform_target": "vk",
            "media_policy": "text_only",
            "media_count": 0,
            "media_asset_ids": [],
            "plan_title": plan_title,
            "publish_time": publish_time,
            "note": "VK photo upload disabled until correct user token is available",
        }
        if dry_run:
            previews.append(
                {
                    "platform": "vk",
                    "title": title,
                    "media_policy": "text_only",
                    "publish_time": publish_time,
                }
            )
        else:
            post = post_repository.create_post(
                db,
                PostCreate(
                    project_id=project.id,
                    media_asset_id=None,
                    title=title,
                    telegram_text=None,
                    vk_text=text,
                    instagram_text=None,
                    hashtags=["teeon", "футболки", "мерч"],
                    seo_keywords=["футболки", "мерч", "производство"],
                    status="needs_review",
                    generation_notes=notes,
                ),
            )
            posts.append(post)
    return posts, previews


# --------------------------------------------------------------------------- #
# Отчёт и точка входа                                                          #
# --------------------------------------------------------------------------- #


def _print_report(
    project: Project,
    today: date,
    today_plans: list[tuple[Any, Any]],
    dry_run: bool,
    tg_posts: list[Post],
    tg_previews: list[dict[str, Any]],
    vk_posts: list[Post],
    vk_previews: list[dict[str, Any]],
    warnings: list[str],
) -> None:
    mode = (
        "dry-run (в БД ничего не записано)" if dry_run else "apply (посты созданы в needs_review)"
    )
    print(f"\nКалендарь на {today.isoformat()} (Europe/Moscow) — {mode}")
    print(f"  проект: {project.name} ({project.slug})")
    if today_plans:
        for category, plan in today_plans:
            print(
                f"  план: {category.title} → {plan.platforms} {plan.publish_times} mode={plan.mode}"
            )
    else:
        print(
            "  ! Плана на сегодня нет — без плана бот ничего не публикует "
            "(черновики созданы для ревью)."
        )

    if dry_run:
        print(f"  Telegram (media-group): будет подготовлено {len(tg_previews)} постов")
        for item in tg_previews:
            print(f"    - {item['title']} · медиа={item['media_count']} · t={item['publish_time']}")
        print(f"  VK (text-only): будет подготовлено {len(vk_previews)} постов")
        for item in vk_previews:
            print(f"    - {item['title']} · время={item['publish_time']}")
    else:
        tg_ids = [p.id for p in tg_posts]
        vk_ids = [p.id for p in vk_posts]
        print(f"  Telegram post_id (needs_review): {tg_ids}")
        print(f"  VK post_id (needs_review): {vk_ids}")

    for warning in warnings:
        print(f"  ! {warning}")

    print("\nСледующие шаги (ручные; ничего не публикуется автоматически):")
    example_id = "<post_id>"
    if not dry_run and (tg_posts or vk_posts):
        example_id = str((tg_posts or vk_posts)[0].id)
    print(f"  python -m app.scripts.review_post --post-id {example_id} --action submit")
    print(f"  python -m app.scripts.schedule_post --post-id {example_id}")
    print(f"  python -m app.scripts.publish_post --post-id {example_id} --dry-run")
    print("  (реальная Telegram-публикация — только отдельной ручной командой после dry-run)")


def run(
    db: Session, service: MediaGroupingService, args: argparse.Namespace
) -> dict[str, Any] | None:
    """Ядро: подготовить посты на сегодня. Вернуть сводку или None при ошибке."""
    dry_run = _parse_bool(args.dry_run)
    today = _resolve_date(args.date)
    try:
        project = resolve_project(db, args.account_id, args.project_slug)
    except CalendarError as exc:
        print(f"Ошибка: {exc}")
        return None

    today_plans = plans_for_today(db, project, today)
    vk_category = _pick_category(db, project, "vk", today_plans)

    tg_plan_title = "Telegram — футболки с фото"
    vk_plan_title = "VK — футболки text-only"
    tg_times = next(
        (list(p.publish_times) for _, p in today_plans if "telegram" in (p.platforms or [])),
        ["12:00", "16:00"],
    )
    vk_times = next(
        (list(p.publish_times) for _, p in today_plans if "vk" in (p.platforms or [])),
        ["17:30"],
    )

    try:
        tg_posts, tg_previews, tg_warnings = prepare_telegram_posts(
            db,
            service,
            args.project_slug,
            args.telegram_media_posts,
            dry_run,
            tg_plan_title,
            tg_times,
        )
    except ProjectNotFoundError as exc:
        print(f"Ошибка: {exc}")
        return None
    vk_posts, vk_previews = prepare_vk_posts(
        db, project, vk_category, args.vk_text_posts, dry_run, vk_plan_title, vk_times
    )

    _print_report(
        project,
        today,
        today_plans,
        dry_run,
        tg_posts,
        tg_previews,
        vk_posts,
        vk_previews,
        tg_warnings,
    )
    return {
        "telegram_post_ids": [p.id for p in tg_posts],
        "vk_post_ids": [p.id for p in vk_posts],
        "telegram_previews": tg_previews,
        "vk_previews": vk_previews,
        "warnings": tg_warnings,
        "dry_run": dry_run,
    }


def main() -> None:
    """Точка входа CLI календаря на сегодня."""
    args = build_parser().parse_args()
    service = get_media_grouping_service()
    factory = get_sessionmaker()
    with factory() as db:
        run(db, service, args)


if __name__ == "__main__":
    main()
