"""Тесты production-валидации конфигурации (без утечки секретов) + статические проверки."""

from pathlib import Path

from app.config import (
    Settings,
    production_ready,
    production_security_errors,
    production_security_warnings,
    security_checks,
    validate_production_settings,
)

_ROOT = Path(__file__).resolve().parents[2]


def _prod(**over: object) -> Settings:
    base: dict[str, object] = {
        "app_env": "production",
        "auth_token_secret": "prod-strong-secret-value-1234567",
        "auth_allow_dev_token": False,
        "auth_require_auth": True,
        "auth_cookie_secure": True,
        "csrf_protection_enabled": True,
        "rate_limit_enabled": True,
    }
    base.update(over)
    return Settings(_env_file=None, **base)


def test_local_not_fatal() -> None:
    loc = Settings(_env_file=None)
    assert production_security_errors(loc) == []
    assert production_ready(loc) is True
    # local: есть предупреждения (dev-токен и т. п.), но не фатальные.
    assert production_security_warnings(loc)


def test_production_missing_secret_errors() -> None:
    errors = production_security_errors(Settings(_env_file=None, app_env="production"))
    assert any("AUTH_TOKEN_SECRET" in e for e in errors)
    assert not production_ready(Settings(_env_file=None, app_env="production"))


def test_production_dev_token_enabled_errors() -> None:
    errors = production_security_errors(_prod(auth_allow_dev_token=True))
    assert any("AUTH_ALLOW_DEV_TOKEN" in e for e in errors)


def test_production_cookie_secure_false_errors() -> None:
    errors = production_security_errors(_prod(auth_cookie_secure=False))
    assert any("AUTH_COOKIE_SECURE" in e for e in errors)


def test_production_sqlite_errors() -> None:
    errors = production_security_errors(_prod(database_url="sqlite:///./x.db"))
    assert any("PostgreSQL" in e or "SQLite" in e for e in errors)


def test_production_live_publishing_errors() -> None:
    errors = production_security_errors(_prod(vk_live_publishing_enabled=True))
    assert any("Live-публикаци" in e for e in errors)


def test_production_ready_when_all_safe() -> None:
    assert production_ready(_prod()) is True
    assert validate_production_settings(_prod()) == []


def test_security_checks_shape() -> None:
    checks = security_checks(_prod())
    keys = {c.key for c in checks}
    for expected in (
        "auth_secret_configured",
        "dev_token_disabled",
        "auth_required",
        "secure_cookies",
        "csrf_enabled",
        "rate_limit_enabled",
        "security_headers_enabled",
        "database_not_sqlite",
        "payments_live_disabled_or_configured",
        "live_publishing_disabled",
        "audit_enabled",
        "paid_actions_enforced",
    ):
        assert expected in keys
    for c in checks:
        assert c.severity in ("info", "warning", "error")


def test_no_secret_in_error_messages() -> None:
    settings = _prod(auth_cookie_secure=False)  # вызовет ошибку, но без секрета
    for msg in production_security_errors(settings):
        assert settings.auth_token_secret not in msg


# --- Часть 13: статические проверки примеров конфигов/деплоя ---


def test_env_production_example_safe() -> None:
    text = (_ROOT / ".env.production.example").read_text(encoding="utf-8")
    assert "AUTH_ALLOW_DEV_TOKEN=false" in text
    assert "PAYMENTS_LIVE_ENABLED=false" in text
    assert "AUTH_REQUIRE_AUTH=true" in text
    assert "AUTH_COOKIE_SECURE=true" in text
    for flag in (
        "TELEGRAM_LIVE_PUBLISHING_ENABLED=false",
        "VK_LIVE_PUBLISHING_ENABLED=false",
        "INSTAGRAM_LIVE_PUBLISHING_ENABLED=false",
    ):
        assert flag in text
    # Нет «реальных» токенов (значения-заглушки пустые или CHANGE_ME).
    assert "vk1." not in text
    assert "EAAG" not in text


def test_docker_compose_prod_example_no_real_secrets() -> None:
    text = (_ROOT / "docker-compose.prod.example.yml").read_text(encoding="utf-8")
    assert "env_file" in text
    assert "CHANGE_ME" in text  # placeholder, не реальный секрет
    assert "vk1." not in text and "EAAG" not in text


def test_readme_links_to_launch_doc() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "30_Botfleet_Public_Launch_Readiness.md" in readme
    assert ".env.production.example" in readme
    assert "docker-compose.prod.example.yml" in readme
    assert "make prod-check" in readme
