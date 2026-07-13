"""Тесты SMTP email-провайдера (v0.5.3). Offline; без сети; фабрика внедряется.

Ключевые гарантии: по умолчанию провайдер ОТКАЗЫВАЕТ (disabled); live-путь достижим только
при всех включённых флагах и использует ВНЕДРЁННУЮ фабрику (реальной сети нет); SMTP-пароль
никогда не попадает в результат/ошибку; destination — только маской.
"""

from typing import Any

from app.config import Settings
from app.services.notification_delivery import NotificationDeliveryRequest
from app.services.notification_delivery.smtp_email_provider import SmtpEmailProvider


def _request(**kw: Any) -> NotificationDeliveryRequest:
    base: dict[str, Any] = {
        "provider": "smtp",
        "channel": "email",
        "recipient_user_id": 1,
        "destination": "user@example.ru",
        "subject": "Тема",
        "message": "Тело письма",
    }
    base.update(kw)
    return NotificationDeliveryRequest(**base)


def _live_settings() -> Settings:
    """Настройки, проходящие ВСЕ гейты SMTP live (для проверки live-пути с фейковой фабрикой)."""
    return Settings(
        notifications_enabled=True,
        notification_delivery_enabled=True,
        notification_external_delivery_enabled=True,
        notification_email_enabled=True,
        notification_email_live_enabled=True,
        smtp_host="smtp.example.com",
        smtp_from_email="noreply@example.com",
        smtp_username="smtpuser",
        smtp_password="s3cr3t-PASSWORD",
        smtp_dry_run=False,
        smtp_live_send_enabled=True,
        smtp_require_tls=True,
    )


class _FakeSmtp:
    """Фейковый SMTP-клиент: НИКАКОЙ сети. Пишет вызовы в общий журнал."""

    def __init__(self, journal: dict[str, Any]) -> None:
        self._journal = journal

    def starttls(self) -> None:
        self._journal["starttls"] = True

    def login(self, username: str, password: str) -> None:
        self._journal["login"] = (username, password)

    def send_message(self, message: Any) -> None:
        self._journal["sent_subject"] = message["Subject"]
        self._journal["sent_to"] = message["To"]

    def quit(self) -> None:
        self._journal["quit"] = True


def test_refuses_by_default_disabled() -> None:
    result = SmtpEmailProvider(Settings()).send(_request())
    assert result.status == "disabled"
    assert result.ok is False


def test_blocked_reason_progression() -> None:
    # Каждый недостающий флаг даёт свою причину отказа; всё включено → None.
    provider = SmtpEmailProvider(Settings())
    assert provider._blocked_reason(Settings()) is not None
    assert provider._blocked_reason(_live_settings()) is None


def test_live_path_uses_injected_factory_no_network() -> None:
    journal: dict[str, Any] = {}
    provider = SmtpEmailProvider(
        _live_settings(), smtp_factory=lambda host, port, timeout: _FakeSmtp(journal)
    )
    result = provider.send(_request())
    assert result.ok is True
    assert result.status == "sent"
    assert result.provider_message_id and result.provider_message_id.startswith("smtp-")
    # Фабрика была вызвана (starttls/login/send/quit) — но это фейк, сети нет.
    assert journal.get("starttls") is True
    assert journal.get("quit") is True
    assert journal.get("sent_subject") == "Тема"


def test_password_never_in_result_or_error() -> None:
    journal: dict[str, Any] = {}
    settings = _live_settings()
    provider = SmtpEmailProvider(
        settings, smtp_factory=lambda host, port, timeout: _FakeSmtp(journal)
    )
    result = provider.send(_request())
    blob = "".join(
        str(x)
        for x in (
            result.status,
            result.error_message,
            result.provider_message_id,
            result.response_metadata,
        )
    )
    assert settings.smtp_password not in blob
    # Пароль передаётся клиенту (login), но не утекает в результат.
    assert journal.get("login") == ("smtpuser", settings.smtp_password)


def test_send_failure_is_sanitized() -> None:
    def _boom(host: str, port: int, timeout: int) -> Any:
        raise OSError("connect failed to smtp.example.com with secret s3cr3t-PASSWORD")

    provider = SmtpEmailProvider(_live_settings(), smtp_factory=_boom)
    result = provider.send(_request())
    assert result.ok is False
    assert result.status == "failed"
    assert "s3cr3t-PASSWORD" not in (result.error_message or "")


def test_destination_masked_in_result() -> None:
    journal: dict[str, Any] = {}
    provider = SmtpEmailProvider(
        _live_settings(), smtp_factory=lambda host, port, timeout: _FakeSmtp(journal)
    )
    result = provider.send(_request(destination="secretmailbox@example.ru"))
    assert "secretmailbox" not in (result.destination_masked or "")
    assert "***" in (result.destination_masked or "")
