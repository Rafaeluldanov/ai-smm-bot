"""Статические safety-проверки email-подсистемы (v0.5.3, Часть 16).

Гарантии на уровне исходников: нет publish_due; нет HTTP-клиентов (smtplib — только в
smtp_email_provider); в CLI/сервисе/UI нет печати сырого SMTP-пароля; тестовая отправка
и live-SMTP выключены по умолчанию; unsubscribe-URL по умолчанию маскируется.
"""

import importlib
import inspect

from app.config import Settings

_EMAIL_MODULES = (
    "app.services.email_template_service",
    "app.repositories.email_template_repository",
    "app.api.email_templates",
    "app.scripts.email_template_preview",
    "app.scripts.email_notification_preview",
    "app.scripts.email_test_send",
)
_SMTP_MODULE = "app.services.notification_delivery.smtp_email_provider"


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_email_modules_no_publish_due() -> None:
    for module in (*_EMAIL_MODULES, _SMTP_MODULE):
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due"):
            assert token not in src, f"{token} в {module}"


def test_email_modules_no_http_clients() -> None:
    # HTTP-клиенты запрещены везде; smtplib/socket — только в smtp_email_provider (за флагами).
    http_tokens = ("requests.", "httpx.", "urllib.request", "aiosmtp")
    for module in _EMAIL_MODULES:
        src = _source(module).lower()
        for token in (*http_tokens, "smtplib", "socket."):
            assert token not in src, f"{token} в {module}"


def test_smtp_provider_source_refuses_by_default() -> None:
    src = _source(_SMTP_MODULE)
    # Провайдер имеет явный gate-метод и disabled-результат.
    assert "_blocked_reason" in src
    assert "_disabled_result" in src or "disabled" in src


def test_no_raw_password_print_or_return() -> None:
    # В email-модулях нет печати/логирования сырого пароля.
    for module in (*_EMAIL_MODULES, _SMTP_MODULE):
        src = _source(module)
        assert "print(settings.smtp_password" not in src
        assert "print(self._settings.smtp_password" not in src
        assert 'f"{settings.smtp_password' not in src


def test_cli_defaults_dry_and_masked() -> None:
    from app.scripts import email_notification_preview, email_test_send

    # По умолчанию unsafe-URL выключен (unsubscribe маскируется).
    args = email_notification_preview.build_parser().parse_args(["--notification-id", "1"])
    assert args.show_unsafe_url == "false"
    # test-send CLI требует получателя, тип по умолчанию системный.
    ts = email_test_send.build_parser().parse_args(["--to", "a@e.com"])
    assert ts.template_type == "system_notice"


def test_config_email_defaults_safe() -> None:
    s = Settings()
    assert s.smtp_live_send_enabled is False
    assert s.smtp_dry_run is True
    assert s.email_test_send_enabled is False
    assert s.smtp_live_send_enabled_effective is False
