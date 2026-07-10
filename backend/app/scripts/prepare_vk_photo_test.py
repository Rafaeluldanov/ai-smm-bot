"""CLI: подготовить VK media-group пост с картинками (needs_review; без публикации).

Проверяет текущий ``VK_ACCESS_TOKEN`` через probe-логику (какая API-стратегия
загрузки фото работает: wall/album), БЕЗ OAuth user-token и БЕЗ браузера. Если ни
wall, ни album не работают — НИЧЕГО не создаёт и объясняет причину. Иначе создаёт
media-group пост по тегу «футболка» (``platform_target=vk``, ``media_policy=media_group``,
``vk_photo_upload_strategy=<wall|album>``, status ``needs_review``). Ничего не
публикует и не включает live. Токен не печатается.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.prepare_vk_photo_test \\
      --account-id 2 --project-slug teeon --tag футболка --dry-run true
"""

import argparse
from typing import Any

from sqlalchemy.orm import Session

from app.api.deps import get_media_grouping_service
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.integrations.vk.client import VKPublishingClient
from app.models.crm_bot_smm import CrmSmmResource
from app.models.post import Post
from app.models.project import Project
from app.repositories import crm_bot_smm_repository as crm_repo
from app.scripts.create_today_calendar_posts import CalendarError, resolve_project
from app.services.media_grouping_service import MediaGroupingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _ok(section: dict[str, Any]) -> str:
    if section.get("ok"):
        return "✔"
    return f"✗(code={section.get('error_code')})"


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов подготовки VK photo-теста."""
    parser = argparse.ArgumentParser(description="Подготовить VK media-group пост с картинками")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--project-slug", default="teeon")
    parser.add_argument("--tag", default="футболка")
    parser.add_argument("--dry-run", default="true")
    return parser


def find_vk_resource(db: Session, project: Project) -> CrmSmmResource | None:
    """Найти первый VK-ресурс проекта (для group_id; необязателен)."""
    config = crm_repo.get_config_by_project_id(db, project.id)
    if config is None:
        return None
    for resource in crm_repo.list_resources_by_config(db, config.id):
        if resource.resource_type == "vk":
            return resource
    return None


def _next_commands(post_id: Any) -> None:
    print("\nСледующие шаги (ручные; live VK — только после отдельного подтверждения):")
    print(
        f"  python -m app.scripts.review_post --post-id {post_id} --action approve "
        '--comment "VK фото проверено"'
    )
    print(f"  python -m app.scripts.schedule_post --post-id {post_id} --platform vk")
    print(f"  python -m app.scripts.publish_post --post-id {post_id} --platform vk --dry-run")
    print(
        "  # live VK — только вручную после dry-run (VK_LIVE_PUBLISHING_ENABLED=true "
        "разово в команде, не глобально)"
    )


def _probe_reason(probe: dict[str, Any]) -> str:
    wall = probe.get("wall", {})
    album = probe.get("album", {})
    return (
        f"wall error {wall.get('error_code')} ({wall.get('error_msg')}); "
        f"album error {album.get('error_code')} ({album.get('error_msg')})"
    )


def run(
    db: Session,
    vk_client: VKPublishingClient,
    grouping_service: MediaGroupingService,
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    """Ядро: probe VK-стратегии и подготовка media-group поста. Вернуть сводку или None."""
    dry_run = _parse_bool(args.dry_run)
    try:
        project = resolve_project(db, args.account_id, args.project_slug)
    except CalendarError as exc:
        print(f"Ошибка: {exc}")
        return None

    resource = find_vk_resource(db, project)
    group_id = resource.external_id if resource and resource.external_id else None

    probe = vk_client.probe_photo_strategies(group_id=group_id, allow_upload=False)
    if probe.get("error"):
        print(f"Ошибка probe: {probe['error']}")
        return {"created": False, "reason": "probe_error", "post_id": None, "dry_run": dry_run}
    recommended = str(probe.get("recommended_strategy", "none"))
    print(
        f"VK probe: wall={_ok(probe.get('wall', {}))} album={_ok(probe.get('album', {}))} "
        f"→ recommended={recommended}"
    )
    if recommended == "none":
        reason = _probe_reason(probe)
        print(f"Ни wall, ни album не работают — пост НЕ создан. Причина: {reason}")
        return {
            "created": False,
            "reason": "strategy_none",
            "post_id": None,
            "dry_run": dry_run,
            "strategy": "none",
        }

    try:
        groups = grouping_service.group_project_media(
            db, args.project_slug, tag=args.tag, max_groups=1, limit_media=5
        )
    except ProjectNotFoundError as exc:
        print(f"Ошибка: {exc}")
        return None
    if not groups:
        print(
            f"Медиа по тегу «{args.tag}» не найдено — пост не создан (нужна синхронизация медиа)."
        )
        return {"created": False, "reason": "no_media", "post_id": None, "dry_run": dry_run}

    mode = "dry-run (в БД ничего не записано)" if dry_run else "apply (пост в needs_review)"
    print(
        f"\nVK photo-тест — {mode}; проект {project.name} ({project.slug}), тег «{args.tag}», "
        f"стратегия {recommended}"
    )

    if dry_run:
        draft = grouping_service.build_post_draft_from_group(db, args.project_slug, groups[0])
        print(
            f"  Будет создан VK media-group пост: {draft.title} · "
            f"медиа={draft.generation_notes.get('media_count')} · platform_target=vk · "
            f"vk_photo_upload_strategy={recommended}"
        )
        _next_commands("<new_id>")
        return {
            "created": False,
            "reason": "dry-run",
            "post_id": None,
            "dry_run": True,
            "strategy": recommended,
        }

    post: Post = grouping_service.create_post_from_media_group(
        db, args.project_slug, groups[0], status="needs_review"
    )
    post.generation_notes = {
        **(post.generation_notes or {}),
        "platform_target": "vk",
        "media_policy": "media_group",
        "vk_photo_upload_strategy": recommended,
    }
    db.commit()
    db.refresh(post)
    print(
        f"  Создан VK media-group пост id={post.id} (status={post.status}, стратегия {recommended})"
    )
    _next_commands(post.id)
    return {
        "created": True,
        "reason": None,
        "post_id": post.id,
        "dry_run": False,
        "strategy": recommended,
    }


def _build_vk_client(settings: Any) -> VKPublishingClient:
    """Собрать VK-клиент из настроек для probe (без live; сеть только на probe-вызовах)."""
    return VKPublishingClient(
        token=settings.vk_access_token or None,
        default_target_id=settings.vk_default_group_id,
        photo_upload_strategy=settings.vk_photo_upload_strategy,
        photo_album_id=settings.vk_photo_album_id,
        photo_album_title=settings.vk_photo_album_title,
    )


def main() -> None:
    """Точка входа CLI подготовки VK photo-теста."""
    args = build_parser().parse_args()
    settings = get_settings()
    if not settings.vk_access_token:
        print("VK_ACCESS_TOKEN не задан — probe невозможен, пост не создан.")
        return
    factory = get_sessionmaker()
    with factory() as db:
        run(db, _build_vk_client(settings), get_media_grouping_service(), args)


if __name__ == "__main__":
    main()
