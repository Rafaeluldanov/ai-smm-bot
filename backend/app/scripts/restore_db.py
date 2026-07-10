"""CLI: восстановление PostgreSQL из дампа через pg_restore (осторожно!).

Разрушительная операция — требует ``--confirm RESTORE``. В production дополнительно
требует ``--i-understand-data-loss true``. Пароль передаётся через ``PGPASSWORD`` и НЕ
печатается. Реального восстановления в тестах не происходит.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # noqa: S404 — вызываем доверенный pg_restore без shell
import sys

from app.config import Settings, get_settings
from app.scripts.backup_db import BackupError, _pg_parts


class RestoreRefused(Exception):
    """Восстановление отклонено (нет подтверждения / production без флага)."""


def check_allowed(settings: Settings, confirm: str, understand_data_loss: bool) -> None:
    """Проверить, разрешено ли восстановление. Иначе — ``RestoreRefused``."""
    if confirm != "RESTORE":
        raise RestoreRefused(
            "Восстановление отклонено: требуется --confirm RESTORE (точное значение)."
        )
    if settings.is_production and not understand_data_loss:
        raise RestoreRefused(
            "В production восстановление требует --i-understand-data-loss true "
            "(данные будут перезаписаны)."
        )


def build_restore_command(settings: Settings, backup_path: str) -> list[str]:
    """Собрать argv для pg_restore (пароль в argv НЕ входит)."""
    parts = _pg_parts(settings.database_url)
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "-h",
        parts["host"],
        "-p",
        parts["port"],
        "-U",
        parts["user"],
        "-d",
        parts["dbname"],
        backup_path,
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Восстановление БД из дампа (pg_restore)")
    parser.add_argument("--backup-path", required=True)
    parser.add_argument("--confirm", default="", help="Введите RESTORE для подтверждения")
    parser.add_argument("--i-understand-data-loss", default="false")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    """Точка входа CLI."""
    args = build_parser().parse_args()
    settings = get_settings()
    understand = str(args.i_understand_data_loss).strip().lower() in {"true", "1", "yes"}

    try:
        check_allowed(settings, args.confirm, understand)
    except RestoreRefused as exc:
        print(f"Отклонено: {exc}")
        sys.exit(2)

    try:
        argv = build_restore_command(settings, args.backup_path)
    except BackupError as exc:
        print(f"Ошибка: {exc}")
        sys.exit(1)

    if not os.path.exists(args.backup_path):
        print(f"Ошибка: файл дампа не найден: {args.backup_path}")
        sys.exit(1)

    printable = " ".join(argv)
    if args.dry_run:
        print("[dry-run] Восстановление PostgreSQL:")
        print(f"  Команда: {printable}")
        print("  (PGPASSWORD передаётся через окружение и не печатается)")
        return

    if shutil.which("pg_restore") is None:
        print("Ошибка: pg_restore не найден в PATH.")
        sys.exit(1)
    env = dict(os.environ)
    parts = _pg_parts(settings.database_url)
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]
    result = subprocess.run(argv, env=env, check=False)  # noqa: S603
    if result.returncode != 0:
        print("Ошибка: pg_restore завершился с ошибкой.")
        sys.exit(result.returncode)
    print("Восстановление завершено.")


if __name__ == "__main__":
    main()
