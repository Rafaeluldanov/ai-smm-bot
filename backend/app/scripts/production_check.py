"""CLI: production-readiness чек-лист (без печати секретов).

Печатает те же проверки, что и ``/health/security-readiness``. Exit code:
- 0 — фатальных production-ошибок нет (в local — всегда 0, только предупреждения);
- 2 — есть production-ошибки (небезопасная конфигурация).

Секреты НИКОГДА не печатаются — только «задан/не задан» и суть проверки.
"""

from __future__ import annotations

import sys

from app.config import Settings, get_settings, production_ready, security_checks

_ICON = {"info": "✅", "warning": "⚠️ ", "error": "❌"}


def _yesno(value: bool) -> str:
    return "да" if value else "нет"


def build_report(settings: Settings) -> tuple[str, int]:
    """Собрать текст отчёта и exit-code (0 ok / 2 есть production-ошибки)."""
    checks = security_checks(settings)
    errors = [c for c in checks if c.severity == "error"]
    lines: list[str] = []
    lines.append("Botfleet — production-readiness чек-лист")
    lines.append(f"  APP_ENV: {settings.app_env} (production={settings.is_production})")
    lines.append(f"  База данных: {'sqlite' if settings.database_is_sqlite else 'postgresql'}")
    lines.append(f"  AUTH_TOKEN_SECRET задан: {_yesno(settings.auth_token_secret_configured)}")
    lines.append(f"  Dev-токен отключён: {_yesno(not settings.auth_allow_dev_token)}")
    lines.append(f"  CSRF включён: {_yesno(settings.csrf_protection_enabled)}")
    lines.append(f"  Rate limiting включён: {_yesno(settings.rate_limit_enabled)}")
    lines.append(f"  Security headers: {_yesno(settings.security_headers_enabled)}")
    lines.append(f"  PAYMENTS_LIVE_ENABLED: {_yesno(settings.payments_live_enabled)}")
    live_off = not (
        settings.telegram_live_publishing_enabled
        or settings.vk_live_publishing_enabled
        or settings.instagram_live_publishing_enabled
    )
    lines.append(f"  Live-публикации выключены: {_yesno(live_off)}")
    lines.append(f"  Аудит включён: {_yesno(settings.audit_log_enabled)}")
    lines.append(f"  Платные действия защищены: {_yesno(settings.paid_actions_enforced)}")
    lines.append("")
    lines.append("Проверки:")
    for c in checks:
        lines.append(f"  {_ICON.get(c.severity, '•')} [{c.severity}] {c.key}: {c.message}")
    lines.append("")
    if errors:
        lines.append(f"РЕЗУЛЬТАТ: НЕ готово к production ({len(errors)} фатальных ошибок).")
    elif production_ready(settings):
        extra = "" if settings.is_production else " (local — только предупреждения)"
        lines.append(f"РЕЗУЛЬТАТ: готово{extra}.")
    return "\n".join(lines), (2 if errors else 0)


def main() -> None:
    """Точка входа CLI."""
    report, code = build_report(get_settings())
    print(report)
    sys.exit(code)


if __name__ == "__main__":
    main()
