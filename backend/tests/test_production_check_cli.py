"""Тесты CLI production_check: exit-code и отсутствие утечки секретов."""

from app.config import Settings
from app.scripts.production_check import build_report


def _prod_ok() -> Settings:
    return Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="prod-strong-secret-value-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )


def test_local_exit_0() -> None:
    report, code = build_report(Settings(_env_file=None))
    assert code == 0
    assert "APP_ENV" in report


def test_production_unsafe_exit_2() -> None:
    report, code = build_report(Settings(_env_file=None, app_env="production"))
    assert code == 2
    assert "НЕ готово" in report


def test_production_safe_exit_0() -> None:
    _report, code = build_report(_prod_ok())
    assert code == 0


def test_report_masks_secret() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        auth_token_secret="SUPER-SECRET-CLI-VALUE-1234567",
        auth_allow_dev_token=False,
        auth_require_auth=True,
        auth_cookie_secure=True,
        csrf_protection_enabled=True,
        rate_limit_enabled=True,
    )
    report, _code = build_report(settings)
    assert "SUPER-SECRET-CLI-VALUE-1234567" not in report
    # Секрет отражается только фактом наличия.
    assert "AUTH_TOKEN_SECRET задан: да" in report
