"""CLI: резервная копия PostgreSQL через pg_dump (пароль не печатается).

Только PostgreSQL. Пароль передаётся через переменную окружения ``PGPASSWORD`` и
НИКОГДА не выводится/не логируется. По умолчанию создаётся custom-format дамп
``backups/botfleet_YYYYMMDD_HHMMSS.dump``. Поддерживает ``--dry-run``.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess  # noqa: S404 — вызываем доверенный pg_dump без shell
import sys
from datetime import UTC, datetime
from urllib.parse import unquote, urlparse

from app.config import Settings, get_settings


class BackupError(Exception):
    """Ошибка резервного копирования (не PostgreSQL, нет pg_dump и т. п.)."""


def _pg_parts(database_url: str) -> dict[str, str]:
    """Разобрать DATABASE_URL в параметры pg_dump (без пароля в результате)."""
    parsed = urlparse(database_url)
    scheme = parsed.scheme.split("+", 1)[0]
    if scheme != "postgresql":
        raise BackupError(
            "Резервное копирование поддерживается только для PostgreSQL "
            f"(DATABASE_URL scheme={scheme!r})."
        )
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": unquote(parsed.username or "postgres"),
        "dbname": (parsed.path or "/").lstrip("/") or "postgres",
        "password": unquote(parsed.password or ""),
    }


def build_backup_command(
    settings: Settings, output_dir: str, timestamp: str
) -> tuple[list[str], str]:
    """Собрать (argv для pg_dump, путь выходного файла). Пароль в argv НЕ входит."""
    parts = _pg_parts(settings.database_url)
    output_path = os.path.join(output_dir, f"botfleet_{timestamp}.dump")
    argv = [
        "pg_dump",
        "-Fc",  # custom format (для pg_restore)
        "-h",
        parts["host"],
        "-p",
        parts["port"],
        "-U",
        parts["user"],
        "-d",
        parts["dbname"],
        "-f",
        output_path,
    ]
    return argv, output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Резервная копия БД (PostgreSQL, pg_dump)")
    parser.add_argument("--output-dir", default="backups")
    parser.add_argument("--dry-run", action="store_true", help="Показать план, не выполнять")
    return parser


def main() -> None:
    """Точка входа CLI."""
    args = build_parser().parse_args()
    settings = get_settings()
    try:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        argv, output_path = build_backup_command(settings, args.output_dir, timestamp)
    except BackupError as exc:
        print(f"Ошибка: {exc}")
        sys.exit(1)

    printable = " ".join(argv)  # пароль сюда не попадает
    if args.dry_run:
        print("[dry-run] Резервное копирование PostgreSQL:")
        print(f"  Команда: {printable}")
        print(f"  Файл:    {output_path}")
        print("  (PGPASSWORD передаётся через окружение и не печатается)")
        return

    if shutil.which("pg_dump") is None:
        print("Ошибка: pg_dump не найден в PATH. Установите PostgreSQL client tools.")
        sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)
    env = dict(os.environ)
    parts = _pg_parts(settings.database_url)
    if parts["password"]:
        env["PGPASSWORD"] = parts["password"]
    result = subprocess.run(argv, env=env, check=False)  # noqa: S603
    if result.returncode != 0:
        print("Ошибка: pg_dump завершился с ошибкой.")
        sys.exit(result.returncode)
    print(f"Готово: {output_path}")


if __name__ == "__main__":
    main()
