"""Тесты backup/restore CLI: dry-run, отказ без confirm, пароль не печатается."""

import pytest

from app.config import Settings
from app.scripts.backup_db import BackupError, build_backup_command
from app.scripts.restore_db import RestoreRefused, build_restore_command, check_allowed

_PG_URL = "postgresql+psycopg2://botfleet:secretpw@db:5432/botfleet"


def test_backup_command_path_and_no_password() -> None:
    settings = Settings(_env_file=None, database_url=_PG_URL)
    argv, path = build_backup_command(settings, "backups", "20260101_120000")
    assert path == "backups/botfleet_20260101_120000.dump"
    assert "pg_dump" in argv[0]
    # Пароль НИКОГДА не попадает в argv (передаётся через PGPASSWORD).
    assert not any("secretpw" in a for a in argv)


def test_backup_rejects_non_postgres() -> None:
    settings = Settings(_env_file=None, database_url="sqlite:///./x.db")
    with pytest.raises(BackupError):
        build_backup_command(settings, "backups", "t")


def test_restore_requires_confirm() -> None:
    settings = Settings(_env_file=None, database_url=_PG_URL)
    with pytest.raises(RestoreRefused):
        check_allowed(settings, confirm="", understand_data_loss=True)
    with pytest.raises(RestoreRefused):
        check_allowed(settings, confirm="yes", understand_data_loss=True)


def test_restore_production_requires_data_loss_flag() -> None:
    prod = Settings(
        _env_file=None,
        app_env="production",
        database_url=_PG_URL,
        auth_token_secret="prod-strong-secret-value-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )
    with pytest.raises(RestoreRefused):
        check_allowed(prod, confirm="RESTORE", understand_data_loss=False)
    # С обоими подтверждениями — не бросает.
    check_allowed(prod, confirm="RESTORE", understand_data_loss=True)


def test_restore_command_no_password() -> None:
    settings = Settings(_env_file=None, database_url=_PG_URL)
    argv = build_restore_command(settings, "backups/x.dump")
    assert "pg_restore" in argv[0]
    assert not any("secretpw" in a for a in argv)
