"""Мастер VK OAuth для ЛОКАЛЬНОГО HTTPS (redirect на https://localhost:8443).

Как ``setup_vk_oauth_env``, но redirect указывает на локальный HTTPS-сервер
(``make run-https-local``), а не на туннель. Ставит VK OAuth-поля в ``.env``,
спрашивает ``VK_APP_SECRET`` через ``getpass`` (не печатает), пишет безопасный
отчёт ``tmp/vk_oauth_local_https_report.txt`` (без секретов). ``VK_ACCESS_TOKEN``
не трогается; live не включается.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.setup_vk_oauth_local_https
"""

import getpass
from pathlib import Path

from app.scripts.setup_vk_oauth_env import (
    VK_APP_ID_DEFAULT,
    VK_DEFAULT_GROUP_ID_DEFAULT,
    read_env_value,
    update_env_file,
)

LOCAL_HTTPS_REDIRECT = "https://localhost:8443/integrations/vk/oauth/callback"
FALLBACK_HTTPS_REDIRECT = "https://127.0.0.1:8443/integrations/vk/oauth/callback"
DEFAULT_ENV_PATH = Path(".env")
REPORT_PATH = Path("tmp/vk_oauth_local_https_report.txt")

_SUMMARY_KEYS = (
    "VK_APP_ID",
    "VK_OAUTH_REDIRECT_URI",
    "VK_DEFAULT_GROUP_ID",
    "VK_LIVE_PUBLISHING_ENABLED",
)


def build_updates(secret: str, existing_group_id: str | None) -> dict[str, str]:
    """Собрать VK OAuth-обновления .env для локального HTTPS (без включения live)."""
    updates: dict[str, str] = {
        "VK_APP_ID": VK_APP_ID_DEFAULT,
        "VK_OAUTH_REDIRECT_URI": LOCAL_HTTPS_REDIRECT,
        "VK_LIVE_PUBLISHING_ENABLED": "false",  # никогда не включаем live
    }
    if secret:
        updates["VK_APP_SECRET"] = secret
    if not existing_group_id:
        updates["VK_DEFAULT_GROUP_ID"] = VK_DEFAULT_GROUP_ID_DEFAULT
    return updates


def apply_setup(env_path: Path, secret: str) -> dict[str, str]:
    """Применить обновления к .env и вернуть безопасную сводку (без секрета)."""
    existing_group = read_env_value(env_path, "VK_DEFAULT_GROUP_ID")
    update_env_file(env_path, build_updates(secret, existing_group))
    summary = {key: (read_env_value(env_path, key) or "") for key in _SUMMARY_KEYS}
    summary["VK_APP_SECRET"] = "present" if read_env_value(env_path, "VK_APP_SECRET") else "not set"
    return summary


def build_report(summary: dict[str, str]) -> str:
    """Собрать безопасный отчёт (без секретов) с инструкцией для VK ID."""
    sep = "=" * 40
    return (
        "\n".join(
            [
                sep,
                "VK OAuth (локальный HTTPS) — итог",
                sep,
                f"VK_APP_ID={summary['VK_APP_ID']}",
                f"VK_OAUTH_REDIRECT_URI={summary['VK_OAUTH_REDIRECT_URI']}",
                f"VK_DEFAULT_GROUP_ID={summary['VK_DEFAULT_GROUP_ID']}",
                f"VK_APP_SECRET={summary['VK_APP_SECRET']}",
                f"VK_LIVE_PUBLISHING_ENABLED={summary['VK_LIVE_PUBLISHING_ENABLED']}",
                "",
                sep,
                "VK ID: что вставить",
                sep,
                "Базовый домен:",
                "localhost",
                "Доверенный Redirect URL:",
                LOCAL_HTTPS_REDIRECT,
                "",
                "Запасной вариант (если VK не примет localhost):",
                "Базовый домен: 127.0.0.1",
                f"Доверенный Redirect URL: {FALLBACK_HTTPS_REDIRECT}",
                "",
                sep,
                "Дальше",
                sep,
                "1. make local-https-cert   (если сертификата ещё нет)",
                "2. make run-https-local",
                "3. открыть https://localhost:8443/ui/projects (принять предупреждение браузера)",
                "4. TEEON → VK → Подключить VK → Разрешить → Проверить доступ",
                "",
                "Безопасность: секрет не показан; VK_ACCESS_TOKEN не тронут; live выключен.",
            ]
        )
        + "\n"
    )


def write_report(summary: dict[str, str], path: Path | None = None) -> None:
    """Записать безопасный отчёт (без секретов) в файл."""
    target = path or REPORT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_report(summary), encoding="utf-8")


def main(env_path: Path | None = None) -> None:
    """Точка входа: спросить секрет, записать VK OAuth-поля, отчёт (без секрета)."""
    path = env_path or DEFAULT_ENV_PATH
    secret = getpass.getpass("Вставьте защищённый ключ VK приложения (не отображается): ").strip()
    summary = apply_setup(path, secret)
    print(f"\nОбновлён {path} (секрет не показывается):")
    for key in _SUMMARY_KEYS:
        print(f"  {key}={summary[key]}")
    print(f"  VK_APP_SECRET={summary['VK_APP_SECRET']}")
    write_report(summary)
    print(f"\nОтчёт: {REPORT_PATH}")
    print(f"VK ID → Базовый домен: localhost · Redirect URL: {LOCAL_HTTPS_REDIRECT}")


if __name__ == "__main__":
    main()
