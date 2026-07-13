"""SMTP email-провайдер (live-ready foundation) — v0.5.3.

Реальная отправка ВЫКЛЮЧЕНА по умолчанию: провайдер ОТКАЗЫВАЕТ, пока не включены ВСЕ флаги
(external delivery + email live + SMTP live + SMTP настроен + не dry-run). Только в этом (по
умолчанию недостижимом) режиме используется stdlib ``smtplib``/``email.message``. Для тестов
SMTP-клиент внедряется фабрикой (``smtp_factory``) — реальной сети нет.

БЕЗОПАСНОСТЬ:
- ``SMTP_PASSWORD`` НИКОГДА не логируется и не попадает в результат/ошибку;
- destination — только маской; при любом сбое — sanitized-ошибка без секретов.
"""

from __future__ import annotations

import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from typing import TYPE_CHECKING, Any

from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
    sanitize_error,
)

if TYPE_CHECKING:
    from app.config import Settings

SmtpFactory = Callable[[str, int, int], Any]


def _default_smtp_factory(host: str, port: int, timeout: int) -> smtplib.SMTP:
    """Стандартная фабрика SMTP-клиента (используется ТОЛЬКО в live-режиме за всеми флагами)."""
    return smtplib.SMTP(host, port, timeout=timeout)


class SmtpEmailProvider(NotificationDeliveryProvider):
    """Live-ready SMTP-провайдер: отправляет ТОЛЬКО при всех включённых флагах (иначе отказ)."""

    provider_name = "smtp"
    channel = "email"

    def __init__(
        self, settings: Settings | None = None, smtp_factory: SmtpFactory | None = None
    ) -> None:
        self._settings = settings
        self._smtp_factory = smtp_factory

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Отправить письмо. Отказ (disabled), пока не включены ВСЕ live-флаги SMTP."""
        settings = self._resolve_settings()
        reason = self._blocked_reason(settings)
        if reason is not None:
            return self._disabled_result(request, reason)
        # --- Live-путь: достижим ТОЛЬКО при всех включённых флагах (в MVP — нет). --- #
        try:
            message = self._build_message(settings, request)
            factory = self._smtp_factory or _default_smtp_factory
            client = factory(
                settings.smtp_host, int(settings.smtp_port), settings.smtp_timeout_seconds_safe
            )
            try:
                if settings.smtp_require_tls:
                    client.starttls()
                if settings.smtp_username:
                    # Пароль передаётся клиенту, но НИКОГДА не логируется/не возвращается.
                    client.login(settings.smtp_username, settings.smtp_password)
                client.send_message(message)
            finally:
                client.quit()
        except Exception as exc:  # noqa: BLE001 — сбой не роняет workflow; ошибка санитизируется
            return NotificationDeliveryResult(
                ok=False,
                status="failed",
                provider=self.provider_name,
                channel=self.channel,
                destination_masked=self._masked(request),
                error_message=self._safe_error(settings, str(exc)),
                response_metadata={"delivered": False},
            )
        return NotificationDeliveryResult(
            ok=True,
            status="sent",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            provider_message_id=self._mock_message_id(request).replace("mock-", "smtp-"),
            response_metadata={"delivered": True},
        )

    @staticmethod
    def _safe_error(settings: Any, raw: str) -> str:
        """Санитизировать текст ошибки: убрать токены-провайдеров И явный SMTP-пароль."""
        message = sanitize_error(raw) or "smtp send failed"
        password = (getattr(settings, "smtp_password", "") or "").strip()
        if password and password in message:
            message = message.replace(password, "***")
        return message or "smtp send failed"

    @staticmethod
    def _blocked_reason(settings: Any) -> str | None:
        """Причина отказа (None → все флаги включены). По умолчанию всегда отказ."""
        if not settings.notification_email_enabled_effective:
            return "external email delivery disabled (NOTIFICATION_EMAIL_LIVE_ENABLED=false)"
        if not settings.smtp_configured:
            return "SMTP not configured (SMTP_HOST/SMTP_FROM_EMAIL empty)"
        if settings.smtp_dry_run:
            return "SMTP dry-run (SMTP_DRY_RUN=true)"
        if not settings.smtp_live_send_enabled:
            return "SMTP live send disabled (SMTP_LIVE_SEND_ENABLED=false)"
        return None

    @staticmethod
    def _build_message(settings: Any, request: NotificationDeliveryRequest) -> EmailMessage:
        message = EmailMessage()
        message["Subject"] = request.subject or ""
        message["From"] = settings.smtp_from_email
        message["To"] = request.destination or ""
        message.set_content(request.message or "")
        html_body = (request.metadata or {}).get("html_body")
        if html_body:
            message.add_alternative(html_body, subtype="html")
        return message
