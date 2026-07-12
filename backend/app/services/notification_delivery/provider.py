"""Интерфейс провайдеров доставки уведомлений — v0.5.1.

Определяет запрос/результат доставки и базовый провайдер. Mock-провайдеры НИКОГДА не ходят в
сеть (только пишут результат). Live-провайдеры — skeleton: отказываются, если внешняя доставка
или live-флаг канала выключены; реальная отправка в MVP не реализована и наружу ничего не идёт.

БЕЗОПАСНОСТЬ:
- в результат НЕ попадают токены/секреты/пароли; ``destination`` возвращается ТОЛЬКО маской;
- ошибки санитизируются (без секретов и внутренних путей).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_SECRET_RE = re.compile(
    r"(?i)(?:vk1\.[\w.-]{6,}|EAA[\w]{6,}|\d{6,}:[\w-]{20,}|(?:live|test)_[\w]{12,})"
)


def sanitize_error(text: str | None) -> str | None:
    """Убрать секреты/токены из текста ошибки провайдера."""
    if not text:
        return None
    cleaned = _SECRET_RE.sub("***", str(text))
    return cleaned[:500]


def mask_destination(channel: str, destination: str | None) -> str:
    """Замаскировать адрес доставки для лога/UI (без раскрытия полного значения).

    email: ``s***@domain.ru`` · telegram: ``12***89`` · webhook: только домен.
    """
    value = (destination or "").strip()
    if not value:
        return "—"
    if channel == "email" and "@" in value:
        local, _, domain = value.partition("@")
        head = local[:1] if local else "*"
        return f"{head}***@{domain}"
    if channel == "telegram":
        if len(value) <= 4:
            return "***"
        return f"{value[:2]}***{value[-2:]}"
    if channel == "webhook":
        # Только домен (без пути/секретов).
        m = re.search(r"https?://([^/]+)", value)
        return m.group(1) if m else "webhook"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


@dataclass
class NotificationDeliveryRequest:
    """Запрос на доставку одного уведомления по каналу."""

    provider: str
    channel: str
    recipient_user_id: int | None
    destination: str | None
    subject: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NotificationDeliveryResult:
    """Результат попытки доставки (без секретов; destination только маской)."""

    ok: bool
    status: str
    provider: str
    channel: str
    destination_masked: str
    provider_message_id: str | None = None
    error_message: str | None = None
    response_metadata: dict[str, Any] = field(default_factory=dict)


class NotificationDeliveryProvider:
    """Базовый провайдер доставки. Подклассы: mock (без сети) и live-skeleton (отказ по флагам)."""

    provider_name: str = "mock"
    channel: str = "email"

    def send(self, request: NotificationDeliveryRequest) -> NotificationDeliveryResult:
        """Отправить (или замокать) доставку. Переопределяется в подклассах."""
        raise NotImplementedError

    # --- Хелперы для подклассов ---

    def _masked(self, request: NotificationDeliveryRequest) -> str:
        return mask_destination(self.channel, request.destination)

    def _mock_message_id(self, request: NotificationDeliveryRequest) -> str:
        digest = hashlib.sha1(
            f"{self.channel}|{request.destination}|{request.subject}|{request.message}".encode()
        ).hexdigest()[:12]
        return f"mock-{self.channel}-{digest}"

    def _disabled_result(
        self, request: NotificationDeliveryRequest, reason: str
    ) -> NotificationDeliveryResult:
        return NotificationDeliveryResult(
            ok=False,
            status="disabled",
            provider=self.provider_name,
            channel=self.channel,
            destination_masked=self._masked(request),
            error_message=sanitize_error(reason),
            response_metadata={"delivered": False},
        )
