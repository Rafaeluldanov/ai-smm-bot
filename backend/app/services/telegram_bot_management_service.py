"""Сервис управления Telegram-ботом (webhook/polling) — v0.5.5.

Скелет вызовов Telegram Bot API: setWebhook / deleteWebhook / getWebhookInfo / getUpdates. По
умолчанию — DRY-RUN: реальной сети НЕТ, возвращается санитизированное описание того, что было бы
отправлено. Live-методы ОТКАЗЫВАЮТ, пока не включены все флаги; в live-пути ``httpx``
импортируется лениво, в тестах HTTP-отправитель внедряется (MockTransport / fake sender).

БЕЗОПАСНОСТЬ:
- bot token НИКОГДА не попадает в URL/результат/ошибку/логи (URL наружу — без токена);
- webhook secret token не возвращается (только факт наличия);
- при любом сбое — sanitized-ошибка без секретов.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.services.notification_delivery.provider import sanitize_error

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger(__name__)

# HTTP-отправитель для live-пути: (method, url, payload, timeout) -> ответ провайдера (dict).
HttpSender = Callable[[str, str, dict[str, Any], int], dict[str, Any]]

_TELEGRAM_API = "https://api.telegram.org"


class TelegramBotManagementService:
    """setWebhook/deleteWebhook/getWebhookInfo/getUpdates: dry-run по умолчанию, live за флагами."""

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

    # ------------------------------------------------------------------ #
    # Preview / dry-run                                                  #
    # ------------------------------------------------------------------ #

    def preview_webhook_setup(self) -> dict[str, Any]:
        """Обзор настройки webhook (без вызовов): URL, secret, live-статус, инструкция."""
        settings = self._resolve_settings()
        return {
            "webhook_url": settings.notification_telegram_webhook_public_url_effective,
            "webhook_path": settings.notification_telegram_webhook_path_effective,
            "secret_required": settings.notification_telegram_webhook_secret_required_effective,
            "secret_configured": bool(
                (settings.notification_telegram_webhook_secret_token or "").strip()
            ),
            "would_call_setWebhook": False,
            "live_enabled": (
                settings.notification_telegram_webhook_management_live_enabled_effective
            ),
            "configured": settings.notification_telegram_configured,
            "instructions": [
                "Задайте публичный HTTPS-домен в NOTIFICATION_TELEGRAM_WEBHOOK_PUBLIC_URL.",
                "Настройте bot token в NOTIFICATION_TELEGRAM_BOT_TOKEN (только env).",
                "Включите live-флаги, когда домен готов; в MVP — dry-run.",
            ],
        }

    def set_webhook_dry(
        self, url: str | None = None, secret_token: str | None = None
    ) -> dict[str, Any]:
        """DRY-RUN setWebhook: вернуть санитизированный payload (без сети, без токена в URL)."""
        settings = self._resolve_settings()
        target = (url or settings.notification_telegram_webhook_public_url_effective or "").strip()
        payload = {
            "url": target,
            "secret_token_provided": bool(
                (secret_token or settings.notification_telegram_webhook_secret_token or "").strip()
            ),
            "allowed_updates": ["message", "edited_message", "callback_query"],
        }
        return {
            "method": "setWebhook",
            "dry_run": True,
            "would_send": payload,
            "live_enabled": (
                settings.notification_telegram_webhook_management_live_enabled_effective
            ),
            "note": "Реального вызова Telegram API нет; это dry-run/sandbox.",
        }

    def delete_webhook_dry(self) -> dict[str, Any]:
        """DRY-RUN deleteWebhook (без сети)."""
        settings = self._resolve_settings()
        return {
            "method": "deleteWebhook",
            "dry_run": True,
            "would_send": {"drop_pending_updates": False},
            "live_enabled": (
                settings.notification_telegram_webhook_management_live_enabled_effective
            ),
            "note": "Реального вызова Telegram API нет; это dry-run/sandbox.",
        }

    def get_webhook_info_dry(self) -> dict[str, Any]:
        """DRY-RUN getWebhookInfo (без сети): показывает ожидаемый URL и статус."""
        settings = self._resolve_settings()
        return {
            "method": "getWebhookInfo",
            "dry_run": True,
            "expected_url": settings.notification_telegram_webhook_public_url_effective,
            "secret_configured": bool(
                (settings.notification_telegram_webhook_secret_token or "").strip()
            ),
            "live_enabled": (
                settings.notification_telegram_webhook_management_live_enabled_effective
            ),
            "note": "Реального вызова Telegram API нет; это dry-run/sandbox.",
        }

    def poll_updates_dry(
        self, offset: int | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """DRY-RUN getUpdates (без сети): показывает параметры, которые были бы отправлены."""
        settings = self._resolve_settings()
        return {
            "method": "getUpdates",
            "dry_run": True,
            "would_send": {
                "offset": offset,
                "limit": limit or settings.notification_telegram_polling_limit_safe,
                "timeout": 0,
            },
            "live_enabled": settings.notification_telegram_polling_live_enabled_effective,
            "note": "Реального вызова Telegram API нет; это dry-run/sandbox.",
        }

    # ------------------------------------------------------------------ #
    # Live (за флагами; в MVP недостижимо)                                #
    # ------------------------------------------------------------------ #

    def set_webhook_live(
        self, url: str | None = None, secret_token: str | None = None
    ) -> dict[str, Any]:
        """Реальный setWebhook. ОТКАЗ, пока не включены все флаги (external + mgmt live + token)."""
        settings = self._resolve_settings()
        reason = self._management_blocked_reason(settings)
        if reason is not None:
            return {"ok": False, "status": "disabled", "reason": reason}
        target = (url or settings.notification_telegram_webhook_public_url_effective or "").strip()
        secret = (secret_token or settings.notification_telegram_webhook_secret_token or "").strip()
        payload: dict[str, Any] = {"url": target}
        if secret:
            payload["secret_token"] = secret
        return self._call_live(settings, "setWebhook", payload)

    def poll_updates_live(
        self, offset: int | None = None, limit: int | None = None
    ) -> dict[str, Any]:
        """Реальный getUpdates. ОТКАЗ, пока не включены все флаги (external + polling live)."""
        settings = self._resolve_settings()
        reason = self._polling_blocked_reason(settings)
        if reason is not None:
            return {"ok": False, "status": "disabled", "reason": reason}
        payload = {
            "offset": offset,
            "limit": limit or settings.notification_telegram_polling_limit_safe,
            "timeout": 0,
        }
        return self._call_live(settings, "getUpdates", payload)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _call_live(self, settings: Any, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Вызвать Telegram Bot API (live-путь, за флагами). Токен не логируется/не отдаётся."""
        try:
            token = settings.notification_telegram_bot_token
            url = f"{_TELEGRAM_API}/bot{token}/{method}"
            sender = self._http_sender or _default_http_sender
            response = sender(method, url, payload, 20)
        except Exception as exc:  # noqa: BLE001 — сбой не роняет; ошибка санитизируется без токена
            return {
                "ok": False,
                "status": "failed",
                "method": method,
                "error": self._safe_error(settings, str(exc)),
            }
        return {
            "ok": bool(response.get("ok", False)),
            "status": "sent" if response.get("ok") else "failed",
            "method": method,
            "result_summary": self._summarize(response),
        }

    @staticmethod
    def _summarize(response: dict[str, Any]) -> dict[str, Any]:
        """Краткая безопасная сводка ответа (без сырых данных)."""
        result = response.get("result")
        if isinstance(result, bool):
            return {"result": result}
        if isinstance(result, list):
            return {"count": len(result)}
        if isinstance(result, dict):
            return {"keys": sorted(result.keys())[:10]}
        return {}

    def _safe_error(self, settings: Any, raw: str) -> str:
        message = sanitize_error(raw) or "telegram api call failed"
        token = (getattr(settings, "notification_telegram_bot_token", "") or "").strip()
        if token and token in message:
            message = message.replace(token, "***")
        return message or "telegram api call failed"

    @staticmethod
    def _management_blocked_reason(settings: Any) -> str | None:
        if not settings.notification_external_delivery_enabled_effective:
            return "external delivery disabled (NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false)"
        if not settings.notification_telegram_webhook_management_live_enabled:
            return (
                "webhook management live disabled "
                "(NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_LIVE_ENABLED=false)"
            )
        if settings.notification_telegram_webhook_management_dry_run:
            return (
                "webhook management dry-run (NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_DRY_RUN=true)"
            )
        if not settings.notification_telegram_configured:
            return "telegram bot token not configured (NOTIFICATION_TELEGRAM_BOT_TOKEN empty)"
        return None

    @staticmethod
    def _polling_blocked_reason(settings: Any) -> str | None:
        if not settings.notification_external_delivery_enabled_effective:
            return "external delivery disabled (NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false)"
        if not settings.notification_telegram_polling_live_enabled:
            return "polling live disabled (NOTIFICATION_TELEGRAM_POLLING_LIVE_ENABLED=false)"
        if settings.notification_telegram_polling_dry_run:
            return "polling dry-run (NOTIFICATION_TELEGRAM_POLLING_DRY_RUN=true)"
        if not settings.notification_telegram_configured:
            return "telegram bot token not configured (NOTIFICATION_TELEGRAM_BOT_TOKEN empty)"
        return None


def _default_http_sender(
    method: str, url: str, payload: dict[str, Any], timeout: int
) -> dict[str, Any]:
    """Стандартный HTTP-отправитель (используется ТОЛЬКО в live-режиме за всеми флагами)."""
    import httpx  # noqa: PLC0415 — ленивый импорт: сеть только в недостижимом по умолчанию live-пути

    response = httpx.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return dict(response.json())


def get_telegram_bot_management_service() -> TelegramBotManagementService:
    """DI-фабрика сервиса управления Telegram-ботом."""
    return TelegramBotManagementService()
