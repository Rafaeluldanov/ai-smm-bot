"""Локальный безопасный мастер настройки VK OAuth в ``.env`` (секрет не печатается).

Ставит/обновляет ТОЛЬКО VK OAuth-поля:
- ``VK_APP_ID`` = 54671660 (приложение «AI SMM Bot»);
- ``VK_OAUTH_REDIRECT_URI`` = http://127.0.0.1:8000/integrations/vk/oauth/callback;
- ``VK_APP_SECRET`` — спрашивается через ``getpass`` (не отображается, не печатается);
- ``VK_DEFAULT_GROUP_ID`` = 240102732 (только если пусто);
- ``VK_LIVE_PUBLISHING_ENABLED`` = false (никогда не включаем live).

Безопасность: секрет не выводится и не логируется; ``VK_ACCESS_TOKEN`` не трогается;
live-публикация не включается. ``.env`` не коммитится. Прочие строки ``.env``
сохраняются как есть.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.setup_vk_oauth_env
"""

import getpass
from pathlib import Path

VK_APP_ID_DEFAULT = "54671660"
VK_OAUTH_REDIRECT_URI_DEFAULT = "http://127.0.0.1:8000/integrations/vk/oauth/callback"
VK_DEFAULT_GROUP_ID_DEFAULT = "240102732"
DEFAULT_ENV_PATH = Path(".env")

_SUMMARY_KEYS = (
    "VK_APP_ID",
    "VK_OAUTH_REDIRECT_URI",
    "VK_DEFAULT_GROUP_ID",
    "VK_LIVE_PUBLISHING_ENABLED",
)


def read_env_value(env_path: Path, key: str) -> str | None:
    """Прочитать значение ключа из ``.env`` (или None, если нет)."""
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name, value = stripped.split("=", 1)
            if name.strip() == key:
                return value.strip()
    return None


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    """Идемпотентно обновить/добавить ключи в ``.env``, сохранив остальные строки."""
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip()
            if name in updates:
                out.append(f"{name}={updates[name]}")
                seen.add(name)
                continue
        out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")
    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_updates(secret: str, existing_group_id: str | None) -> dict[str, str]:
    """Собрать словарь VK OAuth-обновлений (без включения live, без токена паблишинга)."""
    updates: dict[str, str] = {
        "VK_APP_ID": VK_APP_ID_DEFAULT,
        "VK_OAUTH_REDIRECT_URI": VK_OAUTH_REDIRECT_URI_DEFAULT,
        "VK_LIVE_PUBLISHING_ENABLED": "false",  # никогда не включаем live
    }
    if secret:
        updates["VK_APP_SECRET"] = secret
    if not existing_group_id:
        updates["VK_DEFAULT_GROUP_ID"] = VK_DEFAULT_GROUP_ID_DEFAULT
    return updates


def _prompt_secret() -> str:
    """Спросить VK_APP_SECRET через getpass (значение не отображается/не печатается)."""
    return getpass.getpass("Вставьте защищённый ключ VK приложения (не отображается): ").strip()


def apply_setup(env_path: Path, secret: str) -> dict[str, str]:
    """Применить обновления к ``.env`` и вернуть безопасную сводку (без секрета)."""
    existing_group = read_env_value(env_path, "VK_DEFAULT_GROUP_ID")
    updates = build_updates(secret, existing_group)
    update_env_file(env_path, updates)
    summary = {key: (read_env_value(env_path, key) or "") for key in _SUMMARY_KEYS}
    summary["VK_APP_SECRET"] = "present" if read_env_value(env_path, "VK_APP_SECRET") else "not set"
    return summary


def main(env_path: Path | None = None) -> None:
    """Точка входа: спросить секрет, записать VK OAuth-поля, показать сводку."""
    path = env_path or DEFAULT_ENV_PATH
    secret = _prompt_secret()
    summary = apply_setup(path, secret)
    print(f"\nОбновлён {path} (секрет не показывается):")
    for key in _SUMMARY_KEYS:
        print(f"  {key}={summary[key]}")
    print(f"  VK_APP_SECRET={summary['VK_APP_SECRET']}")
    print("\nДалее: откройте UI проекта TEEON → VK → «Подключить VK».")


if __name__ == "__main__":
    main()
