"""CLI: показать настройки VK OAuth callback (публичный HTTPS) — без секретов.

Печатает PUBLIC_APP_URL, VK_APP_ID и что вставить в VK ID (базовый домен + доверенный
Redirect URL, выведенный из PUBLIC_APP_URL). Проверяет, что глобальная live-публикация
VK выключена (`VK_LIVE_PUBLISHING_ENABLED=false`). Секреты/токены НЕ печатаются.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.show_vk_oauth_setup
"""

import argparse
from typing import Any

from app.config import Settings, get_settings


def build_info(settings: Settings) -> dict[str, Any]:
    """Собрать безопасную сводку настроек VK OAuth (без секретов)."""
    return {
        "public_app_url": settings.public_app_url,
        "vk_app_id": settings.vk_app_id or "(не задан)",
        "vk_id_base_domain": settings.vk_oauth_base_domain,
        "vk_id_redirect_url": settings.vk_oauth_redirect_uri,
        "vk_oauth_configured": bool(settings.vk_oauth_configured),
        "vk_live_publishing_enabled": bool(settings.vk_live_publishing_enabled),
    }


def print_info(info: dict[str, Any]) -> None:
    """Напечатать сводку (без секретов) и статус live-флага."""
    sep = "=" * 52
    print(sep)
    print("VK OAuth setup — публичный HTTPS callback")
    print(sep)
    print(f"PUBLIC_APP_URL: {info['public_app_url']}")
    print(f"VK_APP_ID:      {info['vk_app_id']}")
    configured = "да" if info["vk_oauth_configured"] else "нет — задайте VK_APP_SECRET в .env"
    print(f"VK OAuth настроен (app_id + secret + redirect): {configured}")
    print()
    print("Вставьте в VK ID → Приложение → Подключение авторизации:")
    print(f"  Базовый домен:           {info['vk_id_base_domain']}")
    print(f"  Доверенный Redirect URL: {info['vk_id_redirect_url']}")
    print()
    if info["vk_live_publishing_enabled"]:
        print(
            "⚠️  VK_LIVE_PUBLISHING_ENABLED=true — глобальная live-публикация ВКЛючена. "
            "Отключите (false): включайте live только разово в команде."
        )
    else:
        print("VK_LIVE_PUBLISHING_ENABLED=false — глобальная live-публикация выключена ✔")
    print("(секреты и токены здесь не показываются)")


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер (аргументы не требуются)."""
    return argparse.ArgumentParser(description="Показать настройки VK OAuth callback")


def main() -> None:
    """Точка входа CLI."""
    build_parser().parse_args()
    print_info(build_info(get_settings()))


if __name__ == "__main__":
    main()
