"""Telegram notification-провайдер (live-ready foundation) — v0.5.4.

Реальная отправка ВЫКЛЮЧЕНА по умолчанию: провайдер ОТКАЗЫВАЕТ, пока не включены ВСЕ флаги
(external delivery + telegram live + telegram live send + bot token настроен). Только в этом (по
умолчанию недостижимом) режиме лениво импортируется ``httpx`` и вызывается Telegram Bot API. Для
тестов HTTP-отправитель внедряется (``http_sender``) — реальной сети нет.

БЕЗОПАСНОСТЬ:
- bot token НИКОГДА не логируется и не попадает в результат/ошибку (URL с токеном не возвращается);
- destination (chat_id) — только маской; при любом сбое — sanitized-ошибка без секретов.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.services.notification_delivery.provider import (
    NotificationDeliveryProvider,
    NotificationDeliveryRequest,
    NotificationDeliveryResult,
    sanitize_error,
)

if TYPE_CHECKING:
    from app.config import Settings

# Отправитель HTTP для live-пути: (url, payload, timeout) -> ответ провайдера (dict).
HttpSender = Callable[[str, dict[str, Any], int], dict[str, Any]]

_TELEGRAM_API = "https://api.telegram.org"


class TelegramNotificationProvider(NotificationDeliveryProvider):
    """Live-ready Telegram-провайдер: отправляет ТОЛЬКО при всех включённых флагах (иначе отказ)."""

    provider_name = "telegram_bot"
    channel = "telegram"

    def __init__(
        self, settings: Settings | None = None, http_sender: HttpSender | None = None
    ) -> None:
        self._settings = settings
        self._http_sender = http_sender

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Отправить сообщение. Отказ (disabled), пока не включены ВСЕ live-флаги Telegram."""
        settings = self._resolve_settings()
        reason = self._blocked_reason(settings)
        if reason is not None:
            return self._disabled_result(request, reason)
        # --- Live-путь: достижим ТОЛЬКО при всех включённых флагах (в MVP — нет). --- #
        try:
            token = settings.notification_telegram_bot_token
            url = f"{_TELEGRAM_API}/bot{token}/sendMessage"
            payload = self._build_payload(settings, request)
            timeout = 20
            sender = self._http_sender or _default_http_sender
            response = sender(url, payload, timeout)
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
        ok = bool(response.get("ok", False))
        message_id = str((response.get("result") or {}).get("message_id") or "")
        return NotificationDeliveryResult(
            ok=ok,
            status="sent" if ok else "failed",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            provider_message_id=f"tg-{message_id}" if ok and message_id else None,
            error_message=None if ok else "telegram send rejected",
            response_metadata={"delivered": ok},
        )

    def _build_payload(self, settings: Any, request: NotificationDeliveryRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": request.destination or "",
            "text": request.message or "",
            "disable_web_page_preview": False,
        }
        parse_mode = str(settings.notification_telegram_parse_mode or "none")
        if parse_mode == "markdown_v2":
            payload["parse_mode"] = "MarkdownV2"
        elif parse_mode == "html":
            payload["parse_mode"] = "HTML"
        return payload

    def _safe_error(self, settings: Any, raw: str) -> str:
        """Санитизировать текст ошибки: убрать токены-провайдеров И явный bot token."""
        message = sanitize_error(raw) or "telegram send failed"
        token = (getattr(settings, "notification_telegram_bot_token", "") or "").strip()
        if token and token in message:
            message = message.replace(token, "***")
        return message or "telegram send failed"

    @staticmethod
    def _blocked_reason(settings: Any) -> str | None:
        """Причина отказа (None → все флаги включены). По умолчанию всегда отказ."""
        if not settings.notification_external_delivery_enabled_effective:
            return "external delivery disabled (NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false)"
        if not settings.notification_telegram_enabled_effective:
            return "telegram live disabled (NOTIFICATION_TELEGRAM_LIVE_ENABLED=false)"
        if not settings.notification_telegram_live_send_enabled:
            return "telegram live send disabled (NOTIFICATION_TELEGRAM_LIVE_SEND_ENABLED=false)"
        if not settings.notification_telegram_configured:
            return "telegram bot token not configured (NOTIFICATION_TELEGRAM_BOT_TOKEN empty)"
        return None


def _default_http_sender(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Стандартный HTTP-отправитель (используется ТОЛЬКО в live-режиме за всеми флагами)."""
    import httpx  # noqa: PLC0415 — ленивый импорт: сеть только в недостижимом по умолчанию live-пути

    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return dict(response.json())
