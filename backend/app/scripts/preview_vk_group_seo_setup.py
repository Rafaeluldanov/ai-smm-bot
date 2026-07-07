"""CLI: превью SEO-заполнения VK-группы (без реальных изменений).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_vk_group_seo_setup \
      --project-slug teeon

Ничего не публикует и не меняет в VK: только предпросмотр описания, статуса,
закрепа, услуг, хэштегов, ссылок, рубрик и предупреждений.
"""

import argparse

from app.services.seo_content_sources import UnknownSeoProjectError
from app.services.vk_group_seo_setup_service import preview_vk_group_setup


def _print_block(title: str, body: str) -> None:
    print(f"\n=== {title} ===")
    print(body)


def main() -> None:
    """Точка входа CLI превью VK-группы."""
    parser = argparse.ArgumentParser(description="Превью SEO-заполнения VK-группы")
    parser.add_argument("--project-slug", default="teeon")
    args = parser.parse_args()

    try:
        preview = preview_vk_group_setup(args.project_slug)
    except UnknownSeoProjectError as exc:
        print(f"Ошибка: {exc}")
        return

    print(f"SEO-превью VK-группы: {preview.project_slug}")
    _print_block("Название группы", preview.group_name)
    _print_block("Статус", preview.status)
    _print_block("Короткое описание", preview.short_description)
    _print_block("Полное описание", preview.full_description)
    _print_block("Закреплённый пост", preview.pinned_post)

    _print_block("SEO-хэштеги", " ".join(preview.hashtags))

    print("\n=== Услуги ===")
    for service in preview.services:
        print(f"  • {service.title} — {service.url}")

    print("\n=== Рубрики ===")
    for rubric in preview.rubrics:
        print(f"  • {rubric}")

    print("\n=== Меню/навигация ===")
    for item in preview.menu:
        print(f"  • {item.title} — {item.url}")

    print("\n=== Ссылки ===")
    for link in preview.links:
        print(f"  • {link}")

    print("\n=== Предупреждения ===")
    for warning in preview.warnings:
        print(f"  ! {warning}")

    print("\nЖивые изменения VK выключены по умолчанию. Применение — только preview/dry-run.")


if __name__ == "__main__":
    main()
